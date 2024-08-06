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
import collections
import logging
import os
import shutil
import time
from functools import partial
from pathlib import Path
from typing import Callable, ClassVar

import pygtail
from pydantic import BaseModel

from cos.core.api import ApiClient
from cos.mods.common.default.handlers.handler_interface import HandlerInterface
from cos.mods.common.default.log_utils import (
    get_end_timestamp,
    get_file_encoding,
    get_start_timestamp,
    get_timestamp_from_line,
    get_timestamp_hint_from_file,
)
from cos.mods.common.default.rule_executor import LogMessageDataItem, RuleDataItem, RuleExecutor

_log = logging.getLogger(__name__)


class LogHandler(BaseModel, HandlerInterface):
    # src_dirs is a list of directories to scan for log files
    src_dirs: ClassVar[list[Path]] = []

    def __str__(self):
        return "LOG Handler"

    @staticmethod
    def supports_static() -> bool:
        return False

    def check_file_path(self, file_path: Path) -> bool:
        return file_path.is_file() and file_path.name.endswith(".log")

    def update_path_state(self, file_path: Path, update_func: Callable[[Path, dict], None]):
        start_time = get_start_timestamp(file_path)
        if start_time is None:
            _log.warning(f"Failed to get start timestamp for log file: {file_path}.")
            update_func(
                file_path,
                {
                    "size": file_path.stat().st_size,
                    "unsupported": True,
                },
            )
            return
        end_time = get_end_timestamp(file_path)
        if end_time is None:
            _log.warning(f"Failed to get end timestamp for log file: {file_path}.")
            update_func(
                file_path,
                {
                    "size": file_path.stat().st_size,
                    "unsupported": True,
                },
            )
            return
        update_func(
            file_path,
            {
                "size": file_path.stat().st_size,
                "start_time": start_time,
                "end_time": end_time,
            },
        )

    def msg_iterator(self, file_path: Path):
        _log.warning("==> This method is not supported for log handler")
        return

    @classmethod
    def update_dirs_to_scan(cls, dirs_to_scan: list[Path]):
        # check if there's any change in the directories to scan
        if collections.Counter(cls.src_dirs) == collections.Counter(dirs_to_scan):
            return

        cls.src_dirs = dirs_to_scan
        _log.info(f"==> Updated directories to scan: {cls.src_dirs}")

    def scan_dirs(self):
        _log.info(f"==> Start searching files in {self.src_dirs}")
        tail_dict = dict()
        for src_dir in self.src_dirs:
            tail_dict = self.__update_tail_dict(tail_dict, src_dir, is_init=True)
        latest_timestamps = dict()

        while True:
            for src_dir in self.src_dirs:
                tail_dict = self.__update_tail_dict(tail_dict, src_dir)
                # Sleep for 5 seconds to avoid too frequent operations
                time.sleep(5)
                for filename, (tail, hint) in tail_dict.items():
                    try:
                        for line in tail:
                            timestamp = get_timestamp_from_line(line, hint)
                            if timestamp:
                                latest_timestamps[filename] = int(timestamp.timestamp())
                            if filename not in latest_timestamps:
                                continue

                            yield RuleDataItem(
                                os.path.join(src_dir, filename),
                                LogMessageDataItem(line),
                                latest_timestamps[filename],
                                "foxglove.Log",
                            )
                    except FileNotFoundError:
                        _log.warning(f"==> File not found, might be deleted: {filename}")
                        del tail_dict[filename]
                        if filename in latest_timestamps:
                            del latest_timestamps[filename]
                        break

    def scan_dirs_and_diagnose(self, api_client: ApiClient, upload_fn: partial):
        executor_name = "Log Scan Rule Executor"
        rule_executor = RuleExecutor(executor_name, api_client, self.scan_dirs(), upload_fn)
        rule_executor.execute()

    def __update_tail_dict(self, tail_dict: dict, dir_path: Path, is_init: bool = False):
        for entry_path in dir_path.iterdir():
            if not self.check_file_path(entry_path):
                continue
            filename_abs = str(entry_path.absolute())
            if filename_abs not in tail_dict:
                _log.info(f"==> New file found{' when initializing' if is_init else ''}: {filename_abs}")

                if not get_start_timestamp(entry_path) or not get_end_timestamp(entry_path):
                    _log.warning(f"==> Failed to get start or end timestamp for {filename_abs}")
                    tail_dict[filename_abs] = ([], None)
                    continue

                file_encoding = get_file_encoding(entry_path)
                tail_dict[filename_abs] = (
                    pygtail.Pygtail(
                        filename_abs,
                        save_on_end=False,
                        read_from_end=is_init,
                        encoding=file_encoding,
                    ),
                    get_timestamp_hint_from_file(entry_path, file_encoding),
                )
        return tail_dict

    @staticmethod
    def prepare_cut(src_file_path: Path, target_dir: Path, start_time: int, end_time: int) -> str:
        """TODO Slice log file and return the path of the sliced file"""
        transcode_chunk_size = 1024 * 1024
        dst_file_path = target_dir / src_file_path.name
        file_encoding = get_file_encoding(src_file_path)
        if file_encoding == "utf8":
            shutil.copy(src_file_path, dst_file_path)
        else:
            with open(src_file_path, "r", encoding=file_encoding) as src_f:
                with open(dst_file_path, "w", encoding="utf8") as dst_f:
                    chunk = src_f.read(transcode_chunk_size)
                    while chunk:
                        dst_f.write(chunk)
                        chunk = src_f.read(transcode_chunk_size)
        return str(dst_file_path.absolute())
