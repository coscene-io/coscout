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
import time
from pathlib import Path

from pydantic import BaseModel

from cos.core.api import ApiClientConfig, get_client
from cos.core.models import RawDeviceCache
from cos.version import get_version

_log = logging.getLogger(__name__)


class RegisterConfig(BaseModel):
    interval_in_secs: int = 60


class Register:
    def __init__(self, api_conf: ApiClientConfig, conf: RegisterConfig):
        self.conf = conf
        self.api_conf = api_conf
        self.api_client = get_client(api_conf)

    def run(self):
        while True:
            raw_device = RawDeviceCache().load_state().dict()
            pubkey = self._get_virmesh_key()
            is_authorized = self.api_client.register_and_authorize_device(**raw_device, tags={"virmesh_pubkey": pubkey})
            if is_authorized:
                self.api_client = get_client(self.api_conf)
                self.setup_cos_version()
                self.setup_virmesh_info()
                return

            time.sleep(self.conf.interval_in_secs)

    def setup_cos_version(self):
        current_version = get_version()
        if current_version is None:
            _log.warning("failed to get current version")
            return

        api_state = self.api_client.state.load_state()
        device = api_state.device
        if not device or not device.get("name"):
            _log.warning("device name not found, skipping")
            return

        tags = api_state.device.get("tags", {})
        remote_version = tags.get("cos_version", "")
        if current_version == remote_version:
            _log.info("cos version already exists, skipping")
            return

        new_tags = tags.copy()
        new_tags["cos_version"] = current_version

        self.api_client.update_device_tags(device["name"], new_tags)
        _log.info("cos version added for device %s", device["name"])

        new_device = self.api_client.get_device(device["name"])
        api_state.device = new_device
        api_state.save_state()
        _log.info("device info updated for device %s", device["name"])

    def setup_virmesh_info(self):
        api_state = self.api_client.state.load_state()
        device = api_state.device
        if not device or not device.get("name"):
            _log.warning("device name not found, skipping")
            return

        tags = api_state.device.get("tags", {})
        virmesh_tag = tags.get("virmesh_pubkey", None)
        if virmesh_tag:
            _log.info("virmesh pubkey already exists, skipping")
            return

        pubkey = self._get_virmesh_key()
        if not pubkey:
            _log.warning("virmesh pubkey not found, skipping")
            return

        new_tags = tags.copy()
        new_tags["virmesh_pubkey"] = pubkey

        self.api_client.update_device_tags(device["name"], new_tags)
        _log.info("virmesh pubkey added for device %s", device["name"])

        new_device = self.api_client.get_device(device["name"])
        api_state.device = new_device
        api_state.save_state()
        _log.info("device info updated for device %s", device["name"])

    def _get_virmesh_key(self) -> str:
        pubkey_file = Path("/etc/virmesh.pub")
        if not pubkey_file.exists():
            _log.warning("virmesh pubkey file not found, skipping")
            return ""

        with pubkey_file.open("r", encoding="utf8") as fp:
            pubkey = fp.read()
            pubkey = pubkey.removeprefix("virmesh").strip()
            if not pubkey:
                _log.warning("virmesh pubkey is empty, skipping")
                return ""
            return pubkey
