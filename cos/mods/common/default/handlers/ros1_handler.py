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
from pathlib import Path
from typing import Callable

from pydantic import BaseModel
from rosbags.highlevel import AnyReader
from rosbags.rosbag1 import Reader as Ros1Reader

from cos.mods.common.default.handlers.handler_interface import HandlerInterface
from cos.mods.common.default.rule_executor import RuleDataItem

_log = logging.getLogger(__name__)


class Ros1Handler(BaseModel, HandlerInterface):
    def __str__(self):
        return "ROS1 Handler"

    @staticmethod
    def supports_static() -> bool:
        return True

    def check_file_path(self, file_path: Path) -> bool:
        return file_path.is_file() and (file_path.name.endswith(".bag") or file_path.name.endswith(".bag.active"))

    def update_path_state(self, file_path: Path, update_func: Callable[[Path, dict], None]):
        with Ros1Reader(file_path) as reader:
            start_time = reader.start_time // 1_000_000_000
            end_time = reader.end_time // 1_000_000_000
            update_func(
                file_path,
                {
                    "size": file_path.stat().st_size,
                    "start_time": start_time,
                    "end_time": end_time,
                },
            )

    @staticmethod
    def __normalize_msgtype(msgtype: str) -> str:
        """Normalize the message type from a/msg/b to a/b"""
        return "/".join(msgtype.split("/msg/"))

    def msg_iterator(self, file_path: Path):
        with AnyReader([file_path]) as reader:
            for connection, timestamp, rawdata in reader.messages():
                try:
                    msg = reader.deserialize(rawdata, connection.msgtype)
                    yield RuleDataItem(
                        topic=connection.topic,
                        msg=msg,
                        ts=timestamp // 1_000_000_000,
                        msgtype=self.__normalize_msgtype(connection.msgtype),
                    )
                except Exception:
                    _log.warning(f"==> failed to deserialize message for {connection.topic}, skipping")
