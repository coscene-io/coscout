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
from typing import Dict, List

import requests
import six as six
from requests.auth import HTTPBasicAuth
from requests.exceptions import RequestException

from cos.core import request_hook
from cos.core.api import ApiClient, ApiClientConfig
from cos.core.exceptions import CosException, Unauthorized

_log = logging.getLogger(__name__)


class RestApiClient(ApiClient):
    def __init__(self, conf: ApiClientConfig):
        """
        :rtype: 返回的将是可以即时调用的ApiClient
        """
        super().__init__(conf)
        self.basic_auth = HTTPBasicAuth("apikey", self.state.api_key)
        self.request_headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        requests.sessions.Session = request_hook.HookSession

    @property
    def api_base(self):
        return self.conf.server_url

    # region organization
    def get_organization(self):
        url = "{api_base}/dataplatform/v1alpha1/organizations/current".format(
            api_base=self.api_base,
        )
        try:
            response = requests.get(url=url, headers=self.request_headers, auth=self.basic_auth, timeout=10)
            if response.status_code == 401:
                raise Unauthorized("Unauthorized")
            result = response.json()
            _log.info("==> Get the organization {org_name}".format(org_name=result.get("name")))
            return result
        except RequestException as e:
            six.raise_from(CosException("Get the organization failed"), e)

    # endregion

    # region project

    def list_device_projects(self, device_name: str):
        """
        :return: 记录的jsons
        """
        url = f"{self.api_base}/dataplatform/v1alpha1/{device_name}/projects"

        try:
            response = requests.get(
                url=url,
                params={"pageSize": 1000},
                headers=self.request_headers,
                auth=self.basic_auth,
                timeout=10,
            )
            if response.status_code == 401:
                raise Unauthorized("Unauthorized")
            response.raise_for_status()

            result = response.json()
            projects = result.get("deviceProjects", [])
            _log.info(f"==> Fetched the device {len(projects)} projects")
            return projects
        except RequestException as e:
            six.raise_from(CosException("List Device Projects failed"), e)

    def _convert_project_slug(self, warehouse_id, proj_slug):
        """
        :param warehouse_id: 数据仓库的uuid
        :param proj_slug: 项目的单个slug，例如 data_project（不带warehouse部份）
        :return: 项目的正则名
        """
        name_mixin_slug = "warehouses/{warehouse_id}/projects/{proj_slug}".format(
            warehouse_id=warehouse_id, proj_slug=proj_slug
        )
        url = "{api_base}/dataplatform/v1alpha1/{name}:convertProjectSlug".format(api_base=self.api_base, name=name_mixin_slug)

        try:
            response = requests.post(
                url=url,
                json={"project": name_mixin_slug},
                headers=self.request_headers,
                auth=self.basic_auth,
                timeout=10,
            )
            if response.status_code == 401:
                raise Unauthorized("Unauthorized")

            result = response.json()
            if result.get("project"):
                _log.info("==> The project name for {slug} is {name}".format(slug=proj_slug, name=result.get("project")))
            else:
                _log.info("==> The project for {slug} does not exist".format(slug=proj_slug))
            return result.get("project")

        except RequestException as e:
            six.raise_from(CosException("Convert Project Slug failed"), e)

    def _convert_warehouse_slug(self, wh_slug):
        """
        :param wh_slug: 数仓的slug
        :return: 数仓的正则名
        """
        name_mixin_slug = "warehouses/" + wh_slug
        url = "{api_base}/dataplatform/v1alpha1/{name}:convertWarehouseSlug".format(
            api_base=self.api_base,
            name=name_mixin_slug,
        )

        try:
            response = requests.post(
                url=url,
                json={"warehouse": name_mixin_slug},
                headers=self.request_headers,
                auth=self.basic_auth,
                timeout=10,
            )
            if response.status_code == 401:
                raise Unauthorized("Unauthorized")

            result = response.json()
            _log.info("==> The warehouse name for {slug} is {name}".format(slug=wh_slug, name=result.get("warehouse")))
            return result.get("warehouse")

        except RequestException as e:
            six.raise_from(CosException("Convert Warehouse Slug failed"), e)

    def project_slug_to_name(self, proj_slug):
        """
        :param: project_full_slug: 项目的slug（代币的意思）<warehouse_slug>/project_slug>, 例如 default/data_project
        :return: 项目的正则名，例如
            warehouses/7ab79a38-49fb-4411-8f1b-dff4ae95b0e5/projects/8793e727-5ed9-4403-98a3-58906a975e55
        """
        # TODO: wh_slug is deprecating, for the moment, it's always default
        wh_slug = "default"
        if "/" in proj_slug:
            _, proj_slug = proj_slug.split("/")

        warehouse_id = self._convert_warehouse_slug(wh_slug).split("/")[1]
        project_name = self._convert_project_slug(warehouse_id, proj_slug)
        if not project_name:
            raise CosException("Project not found: " + proj_slug)
        project_id = project_name.split("/")[3]
        return "warehouses/{warehouse_id}/projects/{project_id}".format(warehouse_id=warehouse_id, project_id=project_id)

    # endregion

    # region config
    def get_configmap(self, config_key, parent_name=None):
        """
        :param parent_name: 父级的名称，例如 org_name 或者 device_name, 默认为 org_name
        :param config_key: 配置的名称
        :return: 配置清单
        """
        url = "{api_base}/dataplatform/v1alpha2/{parent}/configMaps/{config_key}".format(
            api_base=self.api_base,
            parent=parent_name or self.org_name,
            config_key=config_key,
        )

        try:
            response = requests.get(url=url, headers=self.request_headers, auth=self.basic_auth, timeout=10)
            if response.status_code == 401:
                raise Unauthorized("Unauthorized")
            response.raise_for_status()

            result = response.json()
            _log.info("==> Fetched the config {config_name}".format(config_name=result.get("name")))
            return result
        except RequestException as e:
            six.raise_from(CosException("Get Config failed"), e)

    def get_configmap_metadata(self, config_key, parent_name=None):
        """
        :param parent_name: 父级的名称，例如 org_name 或者 device_name, 默认为 org_name
        :param config_key: 配置的名称
        :return: 配置清单
        """
        url = "{api_base}/dataplatform/v1alpha2/{parent}/configMaps/{config_key}/metadata".format(
            api_base=self.api_base,
            parent=parent_name or self.org_name,
            config_key=config_key,
        )

        try:
            response = requests.get(url=url, headers=self.request_headers, auth=self.basic_auth, timeout=10)
            if response.status_code == 401:
                raise Unauthorized("Unauthorized")
            response.raise_for_status()

            result = response.json()
            _log.info("==> Fetched the config metadata {config_name}".format(config_name=result.get("name")))
            return result
        except RequestException as e:
            six.raise_from(CosException("Get Config Metadata failed"), e)

    # endregion

    # region record
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
        url = "{api_base}/dataplatform/v1alpha2/{parent}/records".format(api_base=self.api_base, parent=self.project_name)
        payload = {
            "title": title,
            "description": description,
            "labels": [self.ensure_label(lbl) for lbl in labels or []],
        }
        if device_name:
            payload["device"] = {"name": device_name}

        try:
            response = requests.post(
                url=url,
                json=payload,
                headers=self.request_headers,
                auth=self.basic_auth,
                timeout=10,
            )
            if response.status_code == 401:
                raise Unauthorized("Unauthorized")

            result = response.json()
            if not result or "name" not in result:
                raise CosException(f"Failed to create record: {result}")

            _log.info("==> Created the record {record_name}".format(record_name=result.get("name")))
            return result

        except RequestException as e:
            six.raise_from(CosException("Create Record failed"), e)

    def update_record(self, record_name, title=None, description="", labels=None):
        """
        :param record_name:
        :param title: 记录的现实title
        :param description: 记录的描述
        :param labels: 记录的描述
        :return: 创建的新记录，以json形式呈现
        """
        url = "{api_base}/dataplatform/v1alpha2/{record_name}".format(api_base=self.api_base, record_name=record_name)
        payload = {"name": record_name}
        params = {"updateMask": []}

        def update_path(key, value):
            if value:
                payload[key] = value
                params["updateMask"] += [key]

        update_path("title", title)
        update_path("description", description)
        update_path("labels", [self.ensure_label(lbl) for lbl in labels or []])

        try:
            response = requests.patch(
                url=url,
                json=payload,
                params=params,
                headers=self.request_headers,
                auth=self.basic_auth,
                timeout=10,
            )
            if response.status_code == 401:
                raise Unauthorized("Unauthorized")

            result = response.json()
            if not result or "name" not in result:
                raise CosException(f"Failed to update record: {result}")

            _log.info("==> Updated the record {record_name}".format(record_name=result.get("name")))
            return result

        except RequestException as e:
            six.raise_from(CosException("Failed to update record"), e)

    def get_record(self, record_name):
        """
        :param record_name: 记录的正则名
        :return: 记录的json
        """
        url = "{api_base}/dataplatform/v1alpha2/{project}/records:batchGet".format(
            api_base=self.api_base, project=self.project_name
        )

        try:
            response = requests.get(
                url=url,
                params={"parent": self.project_name, "names": [record_name]},
                headers=self.request_headers,
                auth=self.basic_auth,
                timeout=10,
            )
            if response.status_code == 401:
                raise Unauthorized("Unauthorized")

            result = response.json()
            if len(result.get("records", [])) == 0:
                raise CosException("Record not found: " + record_name)

            result = result.get("records")[0]
            _log.info("==> Fetched the record {record_title}".format(record_title=result.get("title", "")))
            return result
        except RequestException as e:
            six.raise_from(CosException("Get Record failed"), e)

    def generate_record_thumbnail_upload_url(self, record_name: str, expire_duration: int = 3600):
        """
        :param record_name: record name
        :param expire_duration: expire duration in seconds
        :return: upload url
        """
        url = "{api_base}/dataplatform/v1alpha2/{parent}:generateRecordThumbnailUploadUrl".format(
            api_base=self.api_base, parent=record_name
        )
        payload = {
            "expire_duration": {"seconds": expire_duration},
        }

        try:
            response = requests.post(
                url=url,
                json=payload,
                headers=self.request_headers,
                auth=self.basic_auth,
                timeout=10,
            )
            if response.status_code == 401:
                raise Unauthorized("Unauthorized")

            result = response.json()
            url = result.get("preSignedUri")
            _log.info(f"==> Generated a thumbnail upload url for {record_name}")
            return url
        except RequestException as e:
            six.raise_from(CosException("Generate revision failed"), e)

    # endregion

    # region device

    def get_device(self, device_name: str) -> dict:
        """
        :param device_name: device resource name, e.g. "devices/xxx"
        :return: device json
        """
        url = "{api_base}/dataplatform/v1alpha2/{device_name}".format(
            api_base=self.api_base,
            device_name=device_name,
        )

        try:
            response = requests.get(url=url, headers=self.request_headers, auth=self.basic_auth, timeout=10)
            if response.status_code == 401:
                raise Unauthorized("Unauthorized")

            result = response.json()
            _log.info("==> Get the device {device_name}".format(device_name=result.get("name", "")))
            return result
        except RequestException as e:
            six.raise_from(CosException("Get Device failed"), e)

    def update_device_tags(self, device_name: str, tags: dict):
        """
        :param device_name: device resource name, e.g. "devices/xxx"
        :param tags: device tags
        :return: device json
        """
        url = "{api_base}/dataplatform/v1alpha2/{device_name}".format(
            api_base=self.api_base,
            device_name=device_name,
        )

        payload = {
            "name": device_name,
            "tags": tags,
        }
        params = {"updateMask": ["tags"]}

        try:
            response = requests.patch(
                url=url,
                json=payload,
                params=params,
                headers=self.request_headers,
                auth=self.basic_auth,
                timeout=10,
            )
            if response.status_code == 401:
                raise Unauthorized("Unauthorized")

            result = response.json()
            _log.info("==> Update the device {device_name} tags".format(device_name=result.get("name", "UNKNOWN")))
            return result
        except RequestException as e:
            six.raise_from(CosException("Update Device tags failed"), e)

    def register_device(
        self,
        serial_number=None,
        display_name=None,
        description=None,
        labels=None,
        tags=None,
    ):
        """
        :param tags:  device tags
        :param serial_number: device serial number, should be unique
        :param display_name: device display name
        :param description: device description
        :param labels: device labels
        :return: {'device': {'name': 'devices/xxx'}, 'exchangeCode': 'xxx'}
        """
        if not serial_number:
            return None
        url = "{api_base}/dataplatform/v1alpha2/devices:registerDevice".format(
            api_base=self.api_base,
        )
        payload = {
            "device": {
                "display_name": display_name or serial_number,
                "serial_number": serial_number,
                "description": description,
                "labels": labels,
                "tags": tags,
            },
        }
        if self._project_slug:
            payload["projectSlug"] = self._project_slug
        if self._org_slug:
            payload["organizationSlug"] = self._org_slug

        try:
            response = requests.post(
                url=url,
                json=payload,
                headers=self.request_headers,
                timeout=10,
            )
            if response.status_code == 401:
                raise Unauthorized("Unauthorized")

            result = response.json()
            if "device" not in result or "name" not in result.get("device") or "exchangeCode" not in result:
                raise CosException(f"Failed to register device {serial_number}, reso is {result}")
            _log.info("==> register the device {device_name}".format(device_name=result.get("device").get("name", "UNKNOWN")))
            return result
        except RequestException as e:
            six.raise_from(CosException("Create Device failed"), e)

    def exchange_device_auth_token(self, device_name, code):
        """
        :param device_name: device resource name
        :param code: exchange code
        :return: {'deviceAuthToken': 'xxx', 'expiresTime': 'xxx'}
        """
        if not device_name or not code:
            return None
        url = "{api_base}/dataplatform/v1alpha2/{device_name}/authToken:exchange".format(
            api_base=self.api_base,
            device_name=device_name,
        )

        try:
            response = requests.post(
                url=url,
                json={
                    "exchange_code": code,
                },
                headers=self.request_headers,
                timeout=10,
            )
            if response.status_code == 401:
                raise Unauthorized("Unauthorized")

            result = response.json()
            _log.info("==> Exchange the device auth token {device_name}".format(device_name=device_name))
            return result
        except RequestException as e:
            six.raise_from(CosException("Exchange Device Auth Token failed"), e)

    def check_device_status(self, device_name, code):
        """
        :param device_name: device resource name
        :param code: exchange code
        :return: {'exist': 'xxx', 'authorizeState': 'xxx'}
        """
        if not device_name or not code:
            return None
        url = "{api_base}/dataplatform/v1alpha2/{device_name}:checkDeviceStatus".format(
            api_base=self.api_base,
            device_name=device_name,
        )

        try:
            response = requests.get(
                url=url,
                params="exchangeCode={code}".format(code=code),
                headers=self.request_headers,
                timeout=10,
            )
            if response.status_code == 401:
                raise Unauthorized("Unauthorized")

            result = response.json()
            _log.info("==> Check the device status {device_name}".format(device_name=device_name))
            return result
        except RequestException as e:
            six.raise_from(CosException("Check the device status failed"), e)

    def send_heartbeat(self, device_name: str, cos_version: str, network_usage: dict):
        """
        send device heartbeat
        :param device_name: device resource name, e.g. "devices/xxx"
        :param cos_version: cos version
        :return: empty
        """

        if not device_name:
            return None
        url = "{api_base}/dataplatform/v1alpha2/{device_name}:heartbeat".format(
            api_base=self.api_base,
            device_name=device_name,
        )
        data = {
            "cos_version": cos_version,
            "network_usage": {
                "download_bytes": network_usage.get("download_bytes", 0),
                "upload_bytes": network_usage.get("upload_bytes", 0),
            },
        }

        try:
            response = requests.post(url=url, headers=self.request_headers, auth=self.basic_auth, json=data, timeout=10)
            if response.status_code == 401:
                raise Unauthorized("Unauthorized")

            result = response.json()
            _log.info("==> Send device heartbeat {device_name}".format(device_name=device_name))
            return result
        except RequestException as e:
            six.raise_from(CosException("Send device heartbeat failed"), e)

    # endregion

    # region event
    def create_event(
        self,
        record_name,
        display_name: str,
        trigger_time: int,
        description: str = None,
        customized_fields: dict = None,
        device_name: str = None,
        duration: float = 0.0,
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
        if not record_name or not display_name:
            return None
        url = "{api_base}/dataplatform/v1alpha2/{project}/events".format(api_base=self.api_base, project=self.project_name)
        try:
            response = requests.post(
                url=url,
                params={"record": record_name},
                json={
                    "displayName": display_name,
                    "triggerTime": {
                        "seconds": int(trigger_time),
                        "nanos": int(trigger_time % 1 * 1e9),
                    },
                    "duration": {
                        "seconds": int(duration),
                        "nanos": int(duration % 1 * 1e9),
                    },
                    "description": description,
                    "customizedFields": customized_fields or {},
                    "device": {"name": device_name},
                },
                headers=self.request_headers,
                auth=self.basic_auth,
                timeout=10,
            )
            if response.status_code == 401:
                raise Unauthorized("Unauthorized")

            result = response.json()
            _log.info("==> Created the event {event_name}".format(event_name=result.get("displayName", "")))
            return result
        except RequestException as e:
            six.raise_from(CosException("Create Event failed"), e)

    # endregion

    # region file

    def generate_security_token(self, project_name: str, ttl_hash: int = 3600) -> dict:
        """
        :param project_name: 项目名称
        :param ttl_hash: 过期时间
        :return:
        """
        _log.info("==> Generating security token")

        url = "{api_base}/datastorage/v1alpha1/securityTokens:generateSecurityToken".format(api_base=self.api_base)
        payload = {"expireDuration": {"seconds": ttl_hash}, "project": project_name}
        try:
            response = requests.post(
                url=url,
                json=payload,
                headers=self.request_headers,
                auth=self.basic_auth,
                timeout=10,
            )
            if response.status_code == 401:
                raise Unauthorized("Unauthorized")

            response.raise_for_status()
            result = response.json()
            _log.info("==> Generated security token")
            return result
        except RequestException as e:
            six.raise_from(CosException("Request security token failed"), e)

    # endregion

    # region label
    def create_label(self, display_name):
        """
        :param display_name: 标签名称
        :return:
        """
        url = "{api_base}/dataplatform/v1alpha1/{project}/labels".format(api_base=self.api_base, project=self.project_name)
        try:
            response = requests.post(
                url=url,
                json={"displayName": display_name},
                headers=self.request_headers,
                auth=self.basic_auth,
                timeout=10,
            )
            if response.status_code == 401:
                raise Unauthorized("Unauthorized")

            return response.json()
        except RequestException as e:
            six.raise_from(CosException("Create label failed"), e)

    def get_label_by_display_name(self, display_name):
        """
        :param display_name: 标签名称
        :return:
        """
        url = "{api_base}/dataplatform/v1alpha1/{project}/labels".format(api_base=self.api_base, project=self.project_name)
        try:
            response = requests.get(
                url=url,
                params=f'parent={self.project_name}&filter=displayName="{display_name}"&pageSize=100',
                headers=self.request_headers,
                auth=self.basic_auth,
                timeout=10,
            )
            if response.status_code == 401:
                raise Unauthorized("Unauthorized")

            for label in response.json().get("labels"):
                if label.get("displayName") == display_name:
                    return label

            return None
        except RequestException as e:
            six.raise_from(CosException("List labels failed"), e)

    def get_label(self, label_name):
        """
        :param label_name: 标签的 resource_name
        :return:
        """
        url = "{api_base}/dataplatform/v1alpha1/{label_name}".format(api_base=self.api_base, label_name=label_name)
        try:
            response = requests.get(url=url, headers=self.request_headers, auth=self.basic_auth, timeout=10)
            if response.status_code == 401:
                raise Unauthorized("Unauthorized")

            return response.json()
        except RequestException as e:
            six.raise_from(CosException("List label failed"), e)

    def ensure_label(self, display_name):
        """
        :param display_name: 标签名称
        :return:
        """
        label = self.get_label_by_display_name(display_name)
        if not label:
            label = self.create_label(display_name)
        return label

    # endregion

    # region metric
    def counter(self, name, value=1, description=None, extra_labels: Dict[str, str] = None):
        """
        :param name:
        :param value:
        :param description:
        :param extra_labels:
        :return:
        """
        url = "{api_base}/dataplatform/v1alpha1/metrics:incCounter".format(api_base=self.api_base)
        payload = {
            "counter": {
                "name": name,
                "description": description,
                "labels": self._update_labels(extra_labels or {}),
            },
            "value": value,
        }

        try:
            response = requests.post(
                url=url,
                json=payload,
                headers=self.request_headers,
                auth=self.basic_auth,
                timeout=10,
            )
            if response.status_code == 401:
                raise Unauthorized("Unauthorized")

            _log.debug(f"==> Counter emitted: {name}={value}")
        except RequestException as e:
            six.raise_from(CosException(f"==> Counter emitted failed: {name}={value}"), e)

    def timer(self, name, value, description=None, extra_labels: Dict[str, str] = None):
        _log.debug(f"==> Timer not implemented: {name}={value}")

    def gauge(self, name, value, description=None, extra_labels: Dict[str, str] = None):
        _log.debug(f"==> Gauge not implemented: {name}={value}")

    def _update_labels(self, labels: dict):
        """
        :param labels:
        :return:
        """
        final_labels = labels.copy()
        final_labels["project"] = self.project_name
        if self.state.device and self.state.device.get("model"):
            final_labels["device"] = self.state.device["model"]
        return final_labels

    # endregion

    # region diagnosis
    def hit_diagnosis_rule(self, diagnosis_rule, hit, device, upload):
        """
        :param diagnosis_rule: 完整的诊断规则
        :param hit: 触发的诊断规则
        :param device: 触发的设备
        :param upload: 是否上传
        """
        url = "{api_base}/dataplatform/v1alpha2/{diagnosis_rule_name}:hit".format(
            api_base=self.api_base,
            diagnosis_rule_name=diagnosis_rule.get("name", ""),
        )
        payload = {
            "diagnosis_rule": diagnosis_rule,
            "hit": hit,
            "device": device,
            "upload": upload,
        }

        try:
            response = requests.post(
                url=url,
                json=payload,
                headers=self.request_headers,
                auth=self.basic_auth,
                timeout=10,
            )
            if response.status_code == 401:
                raise Unauthorized("Unauthorized")
            response.raise_for_status()

            _log.info(
                "==> Successfully hit diagnosis rule for {diagnosis_rule}".format(
                    diagnosis_rule=diagnosis_rule.get("name", "")
                )
            )
        except RequestException as e:
            six.raise_from(CosException("Hit diagnosisRules failed"), e)

    def count_diagnosis_rules_hit(self, diagnosis_rule, hit, device):
        """
        :param diagnosis_rule: 诊断规则名称
        :param hit: 触发的诊断规则
        :param device: 设备名称
        :return: 返回诊断规则对应的hit数量
        """
        url = "{api_base}/dataplatform/v1alpha2/{diagnosis_rule}:countDiagnosisRuleHits".format(
            api_base=self.api_base,
            diagnosis_rule=diagnosis_rule,
        )
        payload = {"diagnosis_rule": diagnosis_rule, "hit": hit, "device": device}

        try:
            response = requests.post(
                url=url,
                json=payload,
                headers=self.request_headers,
                auth=self.basic_auth,
                timeout=10,
            )
            if response.status_code == 401:
                raise Unauthorized("Unauthorized")
            response.raise_for_status()

            _log.info("==> Fetched diagnosis rule hit counts for {diagnosis_rule}".format(diagnosis_rule=diagnosis_rule))
            return response.json()
        except RequestException as e:
            six.raise_from(CosException("Count diagnosis rules hits failed"), e)

    def get_diagnosis_rules_metadata(self, parent_name: str = None):
        """
        :param parent_name: 项目名称, 若为空则返回组织下的所有诊断规则元信息
        :return: 返回诊断规则元信息
        """
        url = "{api_base}/dataplatform/v1alpha2/{parent}/diagnosisRule/metadata".format(
            api_base=self.api_base,
            parent="warehouses/-/projects/-" if not parent_name else parent_name,
        )

        try:
            response = requests.get(url=url, headers=self.request_headers, auth=self.basic_auth, timeout=10)
            if response.status_code == 401:
                raise Unauthorized("Unauthorized")
            response.raise_for_status()

            result = response.json()
            _log.info("==> Fetched the diagnosis rules metadata {result}".format(result=result.get("name")))
            return result
        except RequestException as e:
            six.raise_from(CosException("Get diagnosisRules Metadata failed"), e)

    def get_diagnosis_rule(self, parent_name: str = None):
        """
        :param parent_name: 项目名称, 若为空则返回组织下的所有诊断规则元信息
        :return: 返回诊断规则元信息
        """
        url = "{api_base}/dataplatform/v1alpha2/{parent}/diagnosisRule".format(
            api_base=self.api_base,
            parent="warehouses/-/projects/-" if not parent_name else parent_name,
        )

        try:
            response = requests.get(url=url, headers=self.request_headers, auth=self.basic_auth, timeout=10)
            if response.status_code == 401:
                raise Unauthorized("Unauthorized")
            response.raise_for_status()

            result = response.json()
            _log.info("==> Fetched the diagnosis rules {result}".format(result=result.get("name")))
            return result
        except RequestException as e:
            six.raise_from(CosException("Get diagnosisRule failed"), e)

    # endregion

    # region task

    def create_task(self, record_name: str, title: str, description: str, assignee: str):
        """
        :param assignee: task 负责人
        :param description: task 描述
        :param title: task 标题
        :param record_name: 关联的 record
        :return:
        """
        url = "{api_base}/dataplatform/v1alpha2/{parent}/tasks".format(
            api_base=self.api_base,
            parent=self.project_name,
        )

        try:
            response = requests.post(
                url=url,
                json={"title": title, "description": description, "assignee": assignee, "record": record_name},
                headers=self.request_headers,
                auth=self.basic_auth,
                timeout=10,
            )
            if response.status_code == 401:
                raise Unauthorized("Unauthorized")
            response.raise_for_status()

            result = response.json()
            _log.info("==> Create the task succeed {task_name}".format(task_name=result.get("name")))
            return result
        except RequestException as e:
            six.raise_from(CosException("Create the task failed"), e)

    def list_device_tasks(self, device_name: str, filter_state: str = None) -> List[Dict]:
        url = "{api_base}/dataplatform/v1alpha3/{parent}/tasks".format(
            api_base=self.api_base,
            parent=device_name,
        )

        try:
            filter_state = "TASK_STATE_UNSPECIFIED" if not filter_state else filter_state
            response = requests.get(
                url=url,
                params=f'parent={device_name}&filter=state="{filter_state}"&pageSize=10',
                headers=self.request_headers,
                auth=self.basic_auth,
                timeout=10,
            )

            if response.status_code == 401:
                raise Unauthorized("Unauthorized")
            response.raise_for_status()

            result = response.json().get("deviceTasks", [])
            _log.info(f"==> Fetched the {len(result)} device tasks")
            return result
        except RequestException as e:
            six.raise_from(CosException("List the device tasks failed"), e)

    def update_task_state(self, task_name: str, state: str):
        url = "{api_base}/dataplatform/v1alpha3/{task_name}".format(
            api_base=self.api_base,
            task_name=task_name,
        )

        payload = {"name": task_name}
        params = {"updateMask": []}

        def update_path(key, value):
            if value:
                payload[key] = value
                params["updateMask"] += [key]

        update_path("state", state)

        try:
            response = requests.patch(
                url=url,
                json=payload,
                params=params,
                headers=self.request_headers,
                auth=self.basic_auth,
                timeout=10,
            )
            if response.status_code == 401:
                raise Unauthorized("Unauthorized")
            response.raise_for_status()

            _log.info("==> Update the task {task_name} state to {state}".format(task_name=task_name, state=state))
        except RequestException as e:
            six.raise_from(CosException("Update the task state failed"), e)

    def put_task_tags(self, task_name: str, tags: dict):
        url = "{api_base}/dataplatform/v1alpha3/{task_name}:addTaskTags".format(
            api_base=self.api_base,
            task_name=task_name,
        )

        payload = {"tags": tags}
        try:
            response = requests.post(
                url=url,
                json=payload,
                headers=self.request_headers,
                auth=self.basic_auth,
                timeout=10,
            )
            if response.status_code == 401:
                raise Unauthorized("Unauthorized")
            response.raise_for_status()

            _log.info("==> Add the task tag succeed {task_name}".format(task_name=task_name))
        except RequestException as e:
            six.raise_from(CosException("Add the task tag failed"), e)

    # endregion
