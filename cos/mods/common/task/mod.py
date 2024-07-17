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
import platform
import uuid
from pathlib import Path

from pydantic import BaseModel
from strictyaml import load

from cos.collector import Mod
from cos.constant import COS_DEFAULT_CONFIG_PATH
from cos.core.api import ApiClient
from cos.core.exceptions import DeviceNotFound
from cos.mods.common.task.task_handler import TaskHandler
from cos.utils import flatten

_log = logging.getLogger(__name__)


class TaskModConfig(BaseModel):
    enabled: bool = False
    sn_file: str | None = ""
    sn_field: str | None = ""
    upload_files: list[str] = []


class TaskMod(Mod):
    _name = "task"

    def __init__(self, api_client: ApiClient, conf: dict = None):
        if not conf:
            _conf = TaskModConfig()
        else:
            _conf = TaskModConfig.model_validate(conf)

        self._api_client = api_client
        self.conf = _conf
        super().__init__()

    def run(self):
        if not self.conf.enabled:
            _log.info("==> Task Mod disabled. skip check folder!")
            return

        if not self.conf.upload_files or len(self.conf.upload_files) == 0:
            _log.info("Task Mod upload files is not set, skip check folder!")
            return

        _log.info("==> Task mod enabled, check upload tasks.")
        TaskHandler(self._api_client, self.conf.upload_files).run()

    def get_device(self):
        if not self.conf.sn_file:
            return self.__generate_device_sn()

        sn_file_path = Path(self.conf.sn_file)
        if not sn_file_path.exists():
            return self.__generate_device_sn()

        file_path_str = str(sn_file_path.absolute())
        if file_path_str.endswith(".txt"):
            with open(sn_file_path, "r", encoding="utf8") as y:
                sn = y.read().strip()
            return {
                "serial_number": sn,
                "display_name": sn,
                "description": sn,
            }
        elif self.conf.sn_field and (
            file_path_str.endswith(".json") or file_path_str.endswith(".yaml") or file_path_str.endswith(".yml")
        ):
            with open(sn_file_path, "r", encoding="utf8") as y:
                try:
                    _data = load(y.read()).data
                    flatten_data = flatten(_data)
                except Exception:
                    _log.error("Failed to load sn file", exc_info=True)
                    return self.__generate_device_sn()
            sn = flatten_data.get(self.conf.sn_field)
            if not sn:
                _log.error("Failed to get sn field", exc_info=True)
                raise DeviceNotFound(f"Failed to get sn field from {sn_file_path}")
            return {
                "serial_number": sn,
                "display_name": sn,
                "description": sn,
            }
        return self.__generate_device_sn()

    def convert_code(self, code_json):
        return {}

    def find_files(self, trigger_time):
        pass

    @staticmethod
    def __generate_device_sn():
        sn_file_path = COS_DEFAULT_CONFIG_PATH.parent / "sn.txt"
        sn_file_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if not sn_file_path.is_file():
                sn = uuid.uuid4().hex
                with open(sn_file_path.absolute(), "w", encoding="utf8") as y:
                    y.write(sn)
        except PermissionError as e:
            raise DeviceNotFound(f"access to {sn_file_path} denied") from e

        with open(sn_file_path.absolute(), "r", encoding="utf8") as y:
            sn = y.read().strip()

        node = platform.node()
        return {
            "serial_number": sn,
            "display_name": f"{node}@{sn}",
            "description": f"node: {node}, sn: {sn}",
        }
