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
from abc import ABCMeta, abstractmethod

from pydantic import BaseModel

from cos.core.exceptions import DeviceNotFound
from cos.core.models import RawDeviceCache

_log = logging.getLogger(__name__)


class ModConfig(BaseModel):
    name: str = "default"
    conf: dict = {}


class Mod(metaclass=ABCMeta):
    _name = "default"
    _mod = {}

    def __init__(self):
        self.raw_device = RawDeviceCache().load_state()
        if not self.raw_device.serial_number:
            device = self.get_device()
            if device is None or not device.get("serial_number"):
                _log.warning("No raw device found, please check robot.yaml is exist, waiting for next scan.")
                raise DeviceNotFound()
            self.raw_device = RawDeviceCache(**device).save_state()

    # For every class that inherits from the current,
    # the class name will be added to plugins
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls._mod[cls._name] = cls

    @staticmethod
    def get_mod(name: str):
        if name not in Mod._mod:
            raise ValueError(f"Mod {name} not found")
        return Mod._mod[name]

    @abstractmethod
    def run(self):
        pass

    @abstractmethod
    def get_device(self):
        pass

    @abstractmethod
    def convert_code(self, code_json):
        pass

    @abstractmethod
    def find_files(self, trigger_time):
        pass
