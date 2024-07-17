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
import shutil
import sys
import time
import traceback
from pathlib import Path
from subprocess import run

import requests
from pydantic import BaseModel, field_validator
from requests import RequestException

from cos.constant import BIN_DIR_PATH, UPDATER_STATE_PATH
from cos.core.models import BaseState
from cos.utils.files import sha256_file
from cos.utils.https import download_file
from cos.version import get_version

_log = logging.getLogger(__name__)


class UpdaterConfig(BaseModel):
    enabled: bool = True
    interval_in_secs: int = 86400
    artifact_base_url: str = None
    binary_path: str = None

    @field_validator("artifact_base_url")
    def check_urls(cls, v):
        if not v.startswith("http"):
            raise ValueError(f"invalid url: {v}")
        return v

    @property
    def binary_name(self):
        if "windows" in self.artifact_base_url:
            return "cos.exe"
        else:
            return "cos"

    @property
    def binary_url(self):
        return f"{self.artifact_base_url}/{self.binary_name}"

    @property
    def version_url(self):
        return f"{self.artifact_base_url}/version"

    @property
    def hash_url(self):
        return f"{self.artifact_base_url}/cos.sha256"


class UpdaterState(BaseState):
    last_update_time: float = 0

    @property
    def state_path(self):
        return UPDATER_STATE_PATH


class Updater:
    def __init__(self, conf: UpdaterConfig, state_path: str = None):
        self.conf = conf
        self.base_dir_path = BIN_DIR_PATH
        self.base_dir_path.mkdir(parents=True, exist_ok=True)

        _state_path = Path(state_path) if state_path else UPDATER_STATE_PATH
        self.state = UpdaterState().load_state(state_path=_state_path)

    def _get_remote_version(self):
        try:
            if self.conf.version_url is None:
                return None

            return requests.get(url=self.conf.version_url, timeout=10).text.strip()
        except RequestException as e:
            _log.error(f"failed to get remote version: {e}")
            return None

    def _check_upgrade(self):
        remote_version = self._get_remote_version()
        if remote_version is None:
            return None, False

        _log.info(f"remote version is {remote_version}")
        current_version = get_version()
        if current_version is None:
            _log.warning("failed to get current version")
            return None, False

        _log.info(f"current version is {current_version}")
        if remote_version.lower() == current_version.lower():
            _log.info(f"current version {current_version} is up-to-date")
            return None, True

        _log.info(f"new version {remote_version} is available")
        return remote_version, True

    def _get_latest_binary(self, target_folder: Path):
        bin_file_path = target_folder / self.conf.binary_name
        hash_file_path = target_folder / "cos.sha256"
        bin_file_path.parent.mkdir(parents=True, exist_ok=True)
        bin_file_path.unlink(missing_ok=True)
        hash_file_path.unlink(missing_ok=True)

        download_file(url=self.conf.binary_url, filename=str(bin_file_path))
        download_file(url=self.conf.hash_url, filename=str(hash_file_path))
        sha256 = sha256_file(bin_file_path)
        with open(hash_file_path, "r", encoding="utf8") as fp:
            expected_sha256 = fp.readline().strip()
        if sha256 != expected_sha256:
            _log.error(f"sha256 mismatch, sha256: {sha256}, expected sha256: {expected_sha256}")
            raise ValueError("sha256 mismatch")
        return str(bin_file_path)

    def _update_binary(self, target_bin: Path):
        if not target_bin.exists():
            raise FileNotFoundError(f"target file {target_bin} does not exist")

        bin_path = Path(self.conf.binary_path)
        if bin_path.exists():
            bin_path.unlink()
        os.link(target_bin, bin_path)
        if os.name == "posix":
            run(["chmod", "+x", str(bin_path)], capture_output=True)

    def _delete_old_bins(self, active_version: str):
        for p in self.base_dir_path.iterdir():
            if p.name.lower() == active_version.lower():
                continue
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                p.unlink()

    def run(self):
        if not self.conf.enabled:
            _log.debug("updater is disabled")
            return
        if self.conf.interval_in_secs + self.state.last_update_time > time.time():
            _log.debug("updater is not due yet")
            return
        try:
            # update last_update_time on latest version check and on successful upgrade
            remote_version, update_success = self._check_upgrade()
            if not update_success:
                _log.info("Failed to check upgrade, will retry later")
                return

            if not remote_version:
                _log.info("newest version is already installed, skipping upgrade")
                self.state.last_update_time = time.time()
                self.state.save_state()
                return

            if self.conf.binary_path is None:
                _log.info("no binary path specified, skipping upgrade")
                return

            _log.info("starting upgrade cos service, deleting old bins")
            target_folder = self.base_dir_path / remote_version
            self._delete_old_bins(remote_version)

            _log.info("downloading latest binary")
            target_bin = self._get_latest_binary(target_folder)

            _log.info("updating binary")
            self._update_binary(Path(target_bin))
            _log.info("upgrade completed, exiting")

            self.state.last_update_time = time.time()
            self.state.save_state()
            sys.exit(0)
        except Exception as e:
            _log.error(f"failed to upgrade service, will retry later, err: {e}, trace: {traceback.print_exc()}")
            return
