# -*- coding:utf-8 -*-
# Copyright 2024 coScene
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import logging
import os
import subprocess
import sys
import time
from abc import ABCMeta, abstractmethod
from pathlib import Path
from subprocess import run
from typing import Dict, List

import boto3
import requests
import six as six
from pydantic import BaseModel
from requests import RequestException
from tqdm import tqdm

from cos.constant import API_CLIENT_STATE_PATH, INSTALL_STATE_PATH
from cos.core.exceptions import CosException, Sha256Mismatch
from cos.core.models import BaseState, FileInfo
from cos.name.project_name import ProjectName
from cos.name.record_name import RecordName
from cos.utils import LimitedFileReader, ProgressLogger, size_fmt
from cos.utils.tools import iso2timestamp
from cos.utils.uploader import S3MultipartUploader

_log = logging.getLogger(__name__)


class ApiClientConfig(BaseModel):
    server_url: str = "https://openapi.coscene.cn"  # the api base url
    project_slug: str | None = None  # the default project slug
    org_slug: str | None = None  # the default organization slug
    type: str = "rest"
    use_cache: bool = True


class InstallState(BaseState):
    init_install: bool = False

    @property
    def state_path(self):
        return INSTALL_STATE_PATH

    def clean_state(self):
        self.init_install = False
        self.save_state()


class ApiClientState(BaseState):
    slug_cache: Dict[str, str] = {}
    device: dict = None
    org_name: str = None
    exchange_code: str = None
    api_key: str = ""
    api_key_expires_at: int = 0

    def registered_device(self, device: dict, exchange_code: str):
        self.device = device
        self.exchange_code = exchange_code
        self.api_key = ""
        self.api_key_expires_at = 0

    def authorized_device(self, expires_time: int, auth_token: str):
        self.api_key_expires_at = expires_time
        self.api_key = auth_token

    @property
    def state_path(self):
        return API_CLIENT_STATE_PATH

    def is_authed(self):
        return self.api_key and self.api_key_expires_at > int(time.time())


class ApiClient(metaclass=ABCMeta):
    def __init__(self, conf: ApiClientConfig):
        if not all([conf.server_url]):
            raise CosException("server_url must not be empty!")
        if not conf.project_slug and not conf.org_slug:
            raise CosException("project_slug and org_slug must not all be empty!")

        self.conf = conf
        self.state = ApiClientState().load_state()
        self.install_state = InstallState().load_state()
        self._project_slug = conf.project_slug
        self._org_slug = conf.org_slug
        self._project_name = None

    # region organization
    @property
    def org_name(self):
        if self.state.org_name:
            return self.state.org_name

        organization = self.get_organization()
        if self.conf.use_cache:
            self.state.org_name = organization.get("name")
            self.state.save_state()
        return organization.get("name")

    @abstractmethod
    def get_organization(self):
        """
        :return: 从服务器获取组织信息
        """
        pass

    # endregion

    # region config
    @abstractmethod
    def get_configmap(self, config_key, parent_name):
        """
        :param parent_name: 父级的名称，例如 org_name 或者 device_name, 默认为 org_name
        :param config_key: 配置的名称
        :return: 配置清单
        """
        pass

    @abstractmethod
    def get_configmap_metadata(self, config_key, parent_name):
        """
        :param parent_name: 父级的名称，例如 org_name 或者 device_name, 默认为 org_name
        :param config_key: 配置的名称
        :return: 配置清单
        """
        pass

    # endregion

    # region project
    @property
    def project_name(self):
        """
        你可以分开输入 <warehouse_uuid> and <project_uuid>
        你也可以输入项目的slug（代币的意思）<warehouse_slug>/project_slug>, 例如 default/data_project
        以下代码会查询服务器，取得对应的 uuid,
        最终API调用的是project name，正则名，将会是 warehouses/<warehouse_uuid>/projects/<project_uuid>
        例如 warehouses/7ab79a38-49fb-4411-8f1b-dff4ae95b0e5/projects/8793e727-5ed9-4403-98a3-58906a975e55

        :return: full project name (warehouses/<uuid>/projects/<uuid>)
        """
        if self._project_name:
            return self._project_name
        if self._project_slug:
            return self._get_project_name_by_slug(self.project_slug)
        return None

    @project_name.setter
    def project_name(self, value):
        self._project_name = value

    @property
    def project_slug(self):
        if self._project_slug:
            return self._project_slug
        return self.conf.project_slug

    @project_slug.setter
    def project_slug(self, value):
        self._project_slug = value

    @property
    def warehouse_name(self):
        return self.project_name.rsplit("/", 2)[0]

    @abstractmethod
    def list_device_projects(self, device_name: str):
        """
        :param device_name: 设备的resource name
        :return: 项目列表
        """
        pass

    @abstractmethod
    def project_slug_to_name(self, proj_slug):
        """
        :param: project_full_slug: 项目的slug（代币的意思）<warehouse_slug>/project_slug>, 例如 default/data_project
        :return: 项目的正则名，例如
            warehouses/7ab79a38-49fb-4411-8f1b-dff4ae95b0e5/projects/8793e727-5ed9-4403-98a3-58906a975e55
        """
        pass

    def _get_project_name_by_slug(self, project_slug: str):
        if project_slug in self.state.slug_cache:
            return self.state.slug_cache[project_slug]

        project_name = self.project_slug_to_name(project_slug)
        if self.conf.use_cache:
            self.state.slug_cache[project_slug] = project_name
            self.state.save_state()
        return project_name

    # endregion

    # region record
    @abstractmethod
    def create_record(
        self,
        file_infos,
        title="Untitled",
        description="",
        labels=None,
        device_name=None,
    ):
        """
        :param file_infos: 文件信息，是用make_file_info函数生成
        :param title: 记录的现实title
        :param description: 记录的描述
        :param labels: 每个记录的显示名称
        :param device_name: 关联的设备
        :return: 创建的新记录，以json形式呈现
        """
        pass

    @abstractmethod
    def update_record(self, record_name, title=None, description="", labels=None):
        """
        :param record_name:
        :param title: 记录的现实title
        :param description: 记录的描述
        :param labels: 记录的描述
        :return: 创建的新记录，以json形式呈现
        """
        pass

    @abstractmethod
    def get_record(self, record_name):
        """
        :param record_name: 记录的正则名
        :return: 记录的json
        """
        pass

    def create_or_get_record(
        self,
        file_infos: List[FileInfo],
        title="Untitled",
        description="",
        labels=None,
        device_name=None,
        record_name=None,
        reserve_file_infos=False,
    ):
        """
        :param title: 记录的标题
        :param description:
        :param file_infos: 需要上传的本地文件清单
        :param labels: 记录的标签
        :param device_name: 关联的设备
        :param record_name: 记录的名称，如果不指定则自动生成
        :param reserve_file_infos: 是否使用已有的文件清单
        :return: 创建的记录
        """
        _log.info("==> Start creating records for Project {project_name}".format(project_name=self.project_name))
        # 1. 计算sha256，生成文件清单
        file_infos = [f.complete(inplace=True) for f in file_infos]

        # 2. 为即将上传的文件创建记录
        if not record_name or str(record_name) == "True":
            record = self.create_record(
                file_infos,
                title,
                description=description,
                labels=labels,
                device_name=device_name,
            )
        else:
            record = self.get_record(record_name)
            # FIXME: 如果文件清单改变，这边不会创建新的revision，在后面申请上传URL的时候会报错

        if reserve_file_infos:
            if "head" not in record:
                _log.warning(f"==> Record {record_name} has no head")
                record["head"] = {}
            if "head" in record:
                if "files" in record["head"]:
                    del record["head"]["files"]
                if "transformation" in record["head"]:
                    del record["head"]["transformation"]
        return record

    @abstractmethod
    def generate_record_thumbnail_upload_url(self, record_name: str, expire_duration: int = 3600):
        """
        :param record_name: 记录的名称
        :param expire_duration: 过期时间
        :return: 生成的上传URL
        """
        pass

    # endregion

    # region device

    @abstractmethod
    def get_device(self, device_name: str) -> dict:
        """
        :param device_name: 设备的resource name
        :return: 设备的json
        """
        pass

    @abstractmethod
    def update_device_tags(self, device_name: str, tags: dict):
        """
        :param device_name: 设备的resource name
        :param tags: 设备的标签
        :return: 更新后的设备，以json形式呈现
        """
        pass

    @abstractmethod
    def register_device(
        self,
        serial_number=None,
        display_name=None,
        description=None,
        labels=None,
        tags=None,
    ):
        """
        :param tags: device tags
        :param serial_number: device serial number
        :param display_name: device display name
        :param description: device description
        :param labels: device labels
        :return: {'device': device, 'exchangeCode': code}
        """
        pass

    @abstractmethod
    def exchange_device_auth_token(self, device_name, code):
        """
        :param device_name: device resource name, e.g. devices/xxx
        :param code: exchange code when registering device
        :return: {'deviceAuthToken': 'xxx', 'expiresTime': 'xxx'}
        """
        pass

    @abstractmethod
    def check_device_status(self, device_name, code):
        """
        :param device_name: device resource name, e.g. devices/xxx
        :param code: exchange code when registering device
        :return: {'exist': 'xxx', 'authorizeState': 'xxx'}
        """
        pass

    def register_and_authorize_device(
        self,
        serial_number=None,
        display_name=None,
        description=None,
        labels=None,
        tags=None,
    ):
        """
        :param serial_number:
        :param display_name:
        :param description:
        :param labels:
        :return: bool, true if device is authorized
        """
        # 0. reload state to get the latest state infos
        self.state.load_state()
        self.install_state.load_state()

        # 1. check if the api key is expiring (Re-auth a day before the token expires)
        dues_at = self.state.api_key_expires_at - 24 * 60 * 60
        if self.state.api_key and dues_at > int(time.time()):
            # The device is authorized and the api key is not expiring
            return True

        # 2. registering device if not already registered
        if not self.state.device or not self.state.exchange_code or self.install_state.init_install:
            result = self.register_device(
                serial_number=serial_number,
                display_name=display_name,
                description=description,
                labels=labels,
                tags=tags,
            )
            self.state.registered_device(result.get("device"), result.get("exchangeCode"))
            self.state.save_state()
            self.install_state.clean_state()
            _log.info(f"Device Registered, waiting for user authorization for the device {serial_number}")
            return False

        # 3. check device status
        device_status = self.check_device_status(self.state.device["name"], self.state.exchange_code)
        if not device_status.get("exist", False):
            _log.info(f"Device {serial_number} already deleted")
            if os.name == "posix":
                res = run(
                    ["systemctl", "stop", "cos.service"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                _log.info("stop cos.service: " + res.stdout)
            return False
        if device_status.get("authorizeState") == "REJECTED":
            _log.info(f"Device {serial_number} is rejected")
            return False

        # 4. get api key
        token_info = self.exchange_device_auth_token(self.state.device["name"], self.state.exchange_code)
        is_authorized = token_info and token_info.get("deviceAuthToken")
        if is_authorized:
            self.state.authorized_device(
                expires_time=iso2timestamp(token_info.get("expiresTime")),
                auth_token=token_info.get("deviceAuthToken"),
            )
            self.state.save_state()
            _log.info(f"The device {serial_number} has been authorized.")
        else:
            _log.info(f"Waiting for user authorization for the device {serial_number}")
        return is_authorized

    @abstractmethod
    def send_heartbeat(self, device_name: str, cos_version: str, network_usage: dict):
        """
        send device heartbeat
        :param device_name: device resource name, e.g. "devices/xxx"
        :param cos_version: cos version
        :param network_usage: network usage
        :return: empty
        """
        pass

    # endregion

    # region event
    @abstractmethod
    def create_event(
        self,
        record_name,
        display_name,
        trigger_time,
        description,
        customized_fields,
        device_name,
        duration,
    ):
        """
        创建event
        :param record_name: record name in the format of
                            "warehouses/{warehouse_id}/projects/{project_id}/records/{record_id}"
        :param display_name:
        :param trigger_time:
        :param description:
        :param customized_fields:
        :param device_name:
        :param duration:
        :return: created event
        """
        pass

    # endregion

    # region files

    @staticmethod
    def upload_file(filepath, upload_url, size_limit=-1):
        """
        :param filepath: 需要上传文件的本地路径
        :param upload_url: 上传用的预签名url
        :param size_limit: 上传文件的大小限制，单位为字节，-1表示不限制
        """
        try:
            if isinstance(filepath, str):
                filepath = Path(filepath)

            with filepath.open("rb") as f:
                if size_limit >= 0:
                    f = LimitedFileReader(f, size_limit)
                    total_size = size_limit
                else:
                    total_size = filepath.stat().st_size

                if sys.stdout.isatty():
                    # 使用tqdm实现进度条，disable=None的时候在非tty环境不显示进度
                    with tqdm.wrapattr(
                        f,
                        "read",
                        total=total_size,
                        unit="B",
                        unit_scale=True,
                        unit_divisor=1024,
                    ) as wrapped_file:
                        response = requests.put(
                            upload_url,
                            data=wrapped_file,
                            headers={"Content-Length": str(total_size)},
                            timeout=10 * 60,
                        )
                else:
                    _log.info(f"==> Uploading {filepath}: {size_fmt(size_limit or total_size)}")
                    response = requests.put(
                        upload_url,
                        data=ProgressLogger(f, total_size, 30),
                        headers={"Content-Length": str(total_size)},
                        timeout=30,
                    )

            if response.text and "Bad sha256" in response.text:
                raise Sha256Mismatch(response.text)
            response.raise_for_status()
            _log.info(f"==> Uploaded {filepath}")
        except RequestException as e:
            six.raise_from(CosException(f"Failed to upload {filepath}"), e)

    @abstractmethod
    def generate_security_token(self, project_name: str, ttl_hash: int = 3600) -> dict:
        """
        :param project_name: 项目的 resource_name
        :param ttl_hash: ttl hash value
        :return: 生成的安全token
        """
        pass

    def resumable_upload_files(self, record_name, file_infos, remove_after=False):
        """
        :param record_name: 记录的 resource_name
        :param file_infos:
        :param remove_after: 上传完成后是否删除本地文件
        :return: 创建的记录
        """
        rc = RecordName.from_str(record_name)
        project_name = ProjectName.with_warehouse_and_project_id(warehouse_id=rc.warehouse_id, project_id=rc.project_id)
        token_dict = self.generate_security_token(project_name=project_name.name, ttl_hash=24 * 60 * 60)
        endpoint_url = token_dict.get("endpoint", "")
        # if endpoint_url is not start with https, we will add it
        if not endpoint_url.startswith("https://"):
            endpoint_url = "https://" + endpoint_url

        session = boto3.session.Session()
        s3_config = boto3.session.Config(retries={"max_attempts": 1, "mode": "standard"})
        s3_client = session.client(
            service_name="s3",
            aws_access_key_id=token_dict.get("accessKeyId", ""),
            aws_secret_access_key=token_dict.get("accessKeySecret"),
            aws_session_token=token_dict.get("sessionToken"),
            endpoint_url=endpoint_url,
            config=s3_config,
        )

        all_completed = True
        file_infos = [f.complete(inplace=True, skip_sha256=True) for f in file_infos]
        sorted_files: List[FileInfo] = sorted(file_infos, key=lambda f: f.size)
        for f in sorted_files:
            try:
                key = rc.simple_record_name() + "/files/" + f.filename
                uploader = S3MultipartUploader(s3_client, bucket="default", file_path=str(f.filepath.absolute()), key=key)
                uploader.upload()
                if remove_after:
                    f.filepath.unlink()
                    _log.info(f"==> Deleted after upload: {f.filepath}")
            except CosException:
                _log.error(
                    f"==> Failed to upload {f.filepath}, will retry later",
                    exc_info=True,
                )
                all_completed = False
        if all_completed:
            _log.info("==> All files uploaded")
        return all_completed

    # endregion

    # region label
    @abstractmethod
    def create_label(self, display_name):
        """
        :param display_name: 标签名称
        :return:
        """
        pass

    @abstractmethod
    def get_label_by_display_name(self, display_name):
        """
        :param display_name: 标签名称
        :return:
        """
        pass

    @abstractmethod
    def get_label(self, label_name):
        """
        :param label_name: 标签的 resource_name
        :return:
        """
        pass

    @abstractmethod
    def ensure_label(self, display_name):
        """
        :param display_name: 标签名称
        :return:
        """
        pass

    # endregion

    # region metrics
    @abstractmethod
    def counter(self, name, value=1, description=None, extra_labels=None):
        """
        :param name:
        :param value:
        :param description:
        :param extra_labels:
        :return:
        """
        pass

    @abstractmethod
    def timer(self, name, value, description=None, extra_labels=None):
        pass

    @abstractmethod
    def gauge(self, name, value, description=None, extra_labels=None):
        pass

    # endregion

    # region diagnosis

    @abstractmethod
    def hit_diagnosis_rule(self, diagnosis_rule, hit, device, upload):
        """
        :param diagnosis_rule: 完整的诊断规则
        :param hit: 触发的诊断规则
        :param device: 触发的设备
        :param upload: 是否上传
        """
        pass

    @abstractmethod
    def count_diagnosis_rules_hit(self, diagnosis_rule, hit, device):
        """
        :param diagnosis_rule: 诊断规则名称
        :param hit: 触发的诊断规则
        :param device: 设备名称
        :return: 返回诊断规则对应的hit数量
        """
        pass

    @abstractmethod
    def get_diagnosis_rules_metadata(self, parent_name: str = None):
        """
        :param parent_name: 父级的名称，project_name
        :return: 规则清单元信息
        """
        pass

    @abstractmethod
    def get_diagnosis_rule(self, parent_name: str = None):
        """
        :param parent_name: 父级的名称，project_name
        :return: 规则清单元信息
        """
        pass

    # endregion

    # region task
    @abstractmethod
    def create_task(self, record_name: str, title: str, description: str, assignee: str | None):
        """
        :param assignee:  任务的执行者
        :param record_name: 记录的resource name
        :param title: 任务的标题
        :param description: 任务的描述
        :return: 创建的任务
        """
        pass

    @abstractmethod
    def list_device_tasks(self, device_name: str, filter_state: str = None) -> List[Dict]:
        """
        :param filter_state: 任务的状态
        :param device_name: 设备的resource name
        :return: 设备的任务列表
        """
        pass

    @abstractmethod
    def update_task_state(self, task_name: str, state: str):
        """
        :param task_name: 任务的resource name
        :param state: 任务的状态
        :return: 更新后的任务
        """
        pass

    @abstractmethod
    def put_task_tags(self, task_name: str, tags: dict):
        """
        :param task_name: 任务的resource name
        :param tags: 任务的标签
        :return: 更新后的任务
        """
        pass

    # endregion


def get_client(api_conf: ApiClientConfig) -> ApiClient:
    if api_conf.type == "rest":
        from cos.core.rest import RestApiClient

        return RestApiClient(api_conf)
    elif api_conf.type == "grpc":
        from cos.core.grpc import GrpcClient

        return GrpcClient(api_conf)
    else:
        raise ValueError(f"Unsupported api client type: {api_conf.type}")
