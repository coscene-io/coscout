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
import logging
import os
import time
from pathlib import Path
from typing import Callable, Dict

from pydantic import BaseModel

from cos.collector.openers import CosHandler
from cos.collector.remote_config import RemoteConfig
from cos.constant import CODE_JSON_CACHE_PATH, CODE_LIMIT_STATE_PATH
from cos.core.api import ApiClient
from cos.utils import download_if_modified

_log = logging.getLogger(__name__)


class EventCodeConfig(BaseModel):
    enabled: bool = False
    whitelist: Dict[str, int] = {}
    reset_interval_in_secs: int = 86400
    code_json_url: str = ""


class RemoteCode(RemoteConfig):
    def __init__(self, api_client: ApiClient, code_json_url: str):
        self._api_client = api_client
        self._code_json_url = code_json_url.removeprefix("cos://")
        super().__init__(enable_cache=True)

    def get_cache_key(self):
        return self._code_json_url

    def get_config_version(self):
        parent_name, config_key = CosHandler.parse_path(self._code_json_url)
        return self._api_client.get_configmap_metadata(parent_name=parent_name, config_key=config_key).get(
            "currentVersion", -1
        )

    def get_config(self):
        parent_name, config_key = CosHandler.parse_path(self._code_json_url)
        return self._api_client.get_configmap(parent_name=parent_name, config_key=config_key).get("value", {})


class EventCodeManager:
    last_reset_timestamp = 0

    def __init__(
        self,
        conf: EventCodeConfig,
        api_client: ApiClient,
        state_path=None,
        convert_code: Callable[[str], Dict[str, str]] = None,
    ):
        self._conf = conf
        self._api_client = api_client

        if conf.enabled and conf.code_json_url:
            self._event_codes = self.load_event_codes(conf, convert_code)
        else:
            conf.enabled = False
            self._event_codes = {}
        self._state_path = Path(state_path) if state_path else CODE_LIMIT_STATE_PATH

    def load_event_codes(
        self,
        conf: EventCodeConfig,
        event_code_converter: Callable[[str], Dict[str, str]] = None,
    ):
        if self._is_http_url(conf.code_json_url):
            _event_codes = json.loads(download_if_modified(conf.code_json_url, filename=CODE_JSON_CACHE_PATH))
        elif self._is_cos_config_url(conf.code_json_url):
            _event_codes = json.loads(self.load_cos_code_config(conf.code_json_url))
        else:
            with open(os.path.expanduser(conf.code_json_url), "rb") as f:
                _event_codes = json.loads(f.read())
        if event_code_converter:
            _event_codes = event_code_converter(_event_codes)
        return _event_codes

    @staticmethod
    def _is_http_url(str_value: str):
        if str_value is None:
            return False
        return str_value.startswith("http://") or str_value.startswith("https://")

    @staticmethod
    def _is_cos_config_url(str_value: str):
        if str_value is None:
            return False
        return str_value.startswith("cos://")

    def load_cos_code_config(self, config_url: str):
        content = RemoteCode(self._api_client, config_url).read_config()
        return json.dumps(content)

    def get_message(self, code, default_error_msg="Unknown Error"):
        return self._event_codes.get(str(code), default_error_msg)

    def _create_or_reset_state(self):
        now = int(time.time())
        if not self.last_reset_timestamp and self._state_path.exists():
            with self._state_path.open("r", encoding="utf8") as fp:
                self.last_reset_timestamp = json.load(fp).get("last_reset_timestamp", 0)
        reset_due_time = self.last_reset_timestamp + self._conf.reset_interval_in_secs

        # reset if reset_due_time is reached or state file is missing
        if now > reset_due_time or not self._state_path.exists():
            # round to the nearest time that is multiple of reset_interval_in_sec
            n = (now - self.last_reset_timestamp) // self._conf.reset_interval_in_secs
            self.last_reset_timestamp += n * self._conf.reset_interval_in_secs
            _log.info("==> Reset code limit state")

            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            with self._state_path.open("w", encoding="utf8") as fp:
                json.dump({"last_reset_timestamp": now}, fp, indent=4, sort_keys=True)

    def hit(self, code):
        if not self._conf.enabled:
            return
        if not code:
            return

        self._create_or_reset_state()
        code = str(code)
        with self._state_path.open("r+", encoding="utf8") as fp:
            states = json.load(fp)
            counters = states.setdefault("counters", {})
            counters[code] = counters.get(code, 0) + 1

            fp.seek(0)
            json.dump(states, fp, indent=4, sort_keys=True)

    def is_over_limit(self, code):
        # code limit is disabled
        if not self._conf.enabled:
            return False

        self._create_or_reset_state()

        if not code:
            _log.error("==> No code found, regard as over limit")
            return True
        code = str(code)

        # code is always over limit if missing in white list
        if code not in self._conf.whitelist:
            _log.warning(f"==> Code {code} not in whitelist, regard as over limit")
            return True

        limit = self._conf.whitelist.get(code)
        # -1 means no limit
        if limit == -1:
            _log.debug(f"==> Code {code} has no limit")
            return False
        with self._state_path.open("r", encoding="utf8") as fp:
            result = json.load(fp)
            counters = result.setdefault("counters", {})
        _log.debug(f"==> Code {code} has been hit {counters.get(code, 0)} times (limit: {limit})")
        return counters.get(code, 0) >= limit
