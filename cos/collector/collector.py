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

import json
import logging.config
import textwrap
from datetime import datetime

from pydantic import BaseModel

from cos.constant import RECORD_DIR_PATH
from cos.core.api import ApiClient
from cos.core.models import FileInfo, RecordCache
from cos.utils import hardlink, is_image
from .codes import EventCodeManager
from ..core import request_hook
from ..core.exceptions import Unauthorized
from ..version import get_version

_log = logging.getLogger(__name__)


class CollectorConfig(BaseModel):
    delete_after_upload: bool = True
    delete_after_interval_in_hours: int = -1
    scan_interval_in_secs: int = 60


class Collector:
    def __init__(
        self,
        conf: CollectorConfig,
        api_client: ApiClient,
        code_manager: EventCodeManager,
    ):
        self.conf = conf
        self.api = api_client
        self.code_mgr = code_manager
        self.device = self.api.state.load_state().device

    def _upload_record_thumbnail(self, record_name, rec_cache: RecordCache):
        for f in rec_cache.file_infos:
            if is_image(f.filename):
                upload_url = self.api.generate_record_thumbnail_upload_url(record_name)
                if upload_url:
                    self.api.upload_file(str(f.filepath), upload_url)
                    return

    def _upload_finish_flag_file(self, record_name, rec_cache: RecordCache) -> bool:
        _finish_file = rec_cache.base_dir_path / "finish.flag"
        if not _finish_file.exists():
            _finish_file.touch()
            with _finish_file.open("w", encoding="utf8") as fp:
                fp.write(json.dumps(rec_cache.files, indent=2))

        file_info = FileInfo(
            filepath=str(_finish_file.absolute()),
            filename=_finish_file.name,
        ).complete(inplace=True)
        return self.api.resumable_upload_files(
            record_name=record_name,
            file_infos=[file_info],
            remove_after=True,
        )

    def __get_record_title(self, rec_cache: RecordCache):
        title = rec_cache.record.get("title", None)
        if title:
            return title
        if rec_cache.task.get("title", None):
            return rec_cache.task.get("title")

        code = rec_cache.event_code
        msg = self.code_mgr.get_message(code)
        trigger_time = datetime.fromtimestamp(rec_cache.timestamp / 1000).isoformat()
        return f'{msg or "未知错误"} ({code}) @ {trigger_time}'

    def __make_record_description(self, title, rec_cache: RecordCache):
        description = rec_cache.record.get("description", None)
        if description:
            return description

        result = textwrap.dedent(
            f"""\
            ### {title}
            the record is triggered @ {rec_cache.timestamp}
            the files are from {rec_cache.base_dir_path}
            on robot:
        """
        )
        if self.device:
            for label in self.device.get("labels", []):
                result += "\n" + label.get("displayName", "")
        return result

    def _create_record_and_event(self, rec_cache: RecordCache):
        record_title = self.__get_record_title(rec_cache)
        record = self.api.create_or_get_record(
            file_infos=rec_cache.file_infos,
            title=record_title,
            description=self.__make_record_description(record_title, rec_cache),
            labels=rec_cache.labels,
            device_name=self.device.get("name"),
            record_name=rec_cache.record.get("name") if rec_cache.record else None,
            reserve_file_infos=True,
        )
        self._upload_record_thumbnail(record.get("name"), rec_cache)

        for moment in rec_cache.moments:
            _ = self.api.create_event(
                record_name=record.get("name"),
                display_name=moment.title if moment.title else record_title,
                description=moment.description if moment.description else record_title,
                customized_fields=moment.metadata,
                trigger_time=moment.timestamp / 1000,
                duration=moment.duration / 1000,
                device_name=self.device["name"],
            )

            if moment.task:
                _ = self.api.create_task(
                    record_name=record.get("name"),
                    title=moment.title if moment.title else record_title,
                    description=moment.description if moment.description else record_title,
                    assignee=moment.task.assignee,
                )

        return record

    def handle_record(self, rec_cache: RecordCache):
        _log.debug(f"==> Checking record: {rec_cache.key}")
        # setup project name
        if rec_cache.project_name:
            self.api.project_name = rec_cache.project_name
        else:
            self.api.project_name = None

        # 0. 如果 skipped，直接退出
        if rec_cache.skipped:
            _log.debug(f"==> Record previously skipped: {rec_cache.key}")

        # 1. 如果还没创建过 record, 检查是否超过了 code limit
        elif not rec_cache.record.get("name") and rec_cache.event_code and self.code_mgr.is_over_limit(rec_cache.event_code):
            _log.warning(f"==> Reached code limit {rec_cache.event_code}, skip handle: {rec_cache.key}")
            task_name = rec_cache.task.get("name", "")
            if task_name:
                self.api.update_task_state(task_name, "SUCCEEDED")

            # 把跳过标记写回到json
            rec_cache.skipped = True
            rec_cache.save_state()
            rec_cache.delete_cache_dir(self.conf.delete_after_interval_in_hours)

        else:
            # 如果没有被 collected (文件未找齐).
            if not rec_cache.record.get("name"):
                # 2. 收集文件，生成 hardlink, 替换FileInfo里filepath为 hardlink 的目标文件（RecordCache.files依然指向原始文件）
                rec_cache.file_infos = [
                    FileInfo(
                        filepath=hardlink(f.filepath.resolve().absolute(), rec_cache.base_dir_path / f.filename),
                        filename=f.filename,
                    ).complete(inplace=True)
                    for f in rec_cache.file_infos
                    if f.filepath.is_file() and f.filename != "finish.flag"
                ]

                # 3. 创建 record 和 event
                rec_cache.record = self._create_record_and_event(rec_cache)
                # 为防止断连后重新建立记录，需要立即写回json
                rec_cache.save_state()
                self.code_mgr.hit(rec_cache.event_code)

            # 找齐文件后，如果还没有 uploaded (上传完毕).
            if not rec_cache.uploaded:
                # 5. 上传文件传输完毕后更新
                filepaths = rec_cache.list_files()
                rec_cache.file_infos = [f for f in rec_cache.file_infos if str(f.filepath) in filepaths]
                all_completed = self.api.resumable_upload_files(
                    record_name=rec_cache.record["name"],
                    file_infos=rec_cache.file_infos,
                    remove_after=True,
                )

                # 6. 完成记录。如果需要，删除 record 文件夹
                if all_completed:
                    if not self._upload_finish_flag_file(rec_cache.record["name"], rec_cache):
                        _log.error(f"==> Failed to upload finish flag file: {rec_cache.key}")
                        return

                    self.api.update_record(
                        record_name=rec_cache.record["name"],
                        labels=rec_cache.labels + ["上传完成"],
                    )
                    task_name = rec_cache.task.get("name", "")
                    if task_name:
                        self.api.put_task_tags(task_name, {"recordName": rec_cache.record.get("name")})
                        self.api.update_task_state(task_name, "SUCCEEDED")

                    rec_cache.uploaded = True
                    rec_cache.save_state()
                    _log.info(f"==> Handled record: {rec_cache.key}")

                    if self.conf.delete_after_upload:
                        rec_cache.delete_cache_dir()

    # noinspection PyBroadException
    def run(self):
        _log.info(f"==> Search for new record in {RECORD_DIR_PATH}")
        total_records = 0
        for record in RecordCache.find_all():
            try:
                self.handle_record(record)
                total_records += 1
            except Unauthorized as e:
                _log.error(f"==> Unauthorized when handling: {record.key}", exc_info=True)
                raise Unauthorized(e)
            except Exception:
                # 打印错误，但保证循环不被打断
                _log.error(f"An error occurred when handling: {record.key}", exc_info=True)

            # 不管上述结果如何，超过一定时间后，删除 record 文件夹
            _log.debug(f"==> Record previously uploaded: {record.key}")
            record.delete_cache_dir(self.conf.delete_after_interval_in_hours)

        if self.device and "name" in self.device:
            current_version = get_version()
            if current_version is None:
                current_version = ""
            self.api.send_heartbeat(
                device_name=self.device["name"],
                cos_version=current_version,
                network_usage={
                    "upload_bytes": request_hook.get_network_upload_usage(),
                    "download_bytes": request_hook.get_network_download_usage(),
                },
            )
            request_hook.reset_network_usage()

        self.api.counter("coscout_collector_run_successful_total")
        self.api.gauge("coscout_collector_record_cache_count", total_records)
