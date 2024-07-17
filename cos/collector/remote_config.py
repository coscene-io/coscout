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
from abc import ABCMeta, abstractmethod

from cos.constant import COS_CACHE_PATH

_log = logging.getLogger(__name__)


class RemoteConfig(metaclass=ABCMeta):
    def __init__(self, enable_cache: bool = True):
        self._enable_cache = enable_cache

    @abstractmethod
    def get_cache_key(self):
        pass

    @abstractmethod
    def get_config_version(self):
        pass

    @abstractmethod
    def get_config(self):
        pass

    def read_config(self) -> dict:
        cache_key = self.get_cache_key()
        cache_file = COS_CACHE_PATH / f"{cache_key}.json"
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        current_version = "-1"
        content = {}
        if self._enable_cache:
            if cache_file.exists():
                with open(str(cache_file), "r", encoding="utf8") as f:
                    content = json.loads(f.read())

            try:
                current_version = self.get_config_version()
            except Exception:
                return content.get("value", {})

            cache_version = content.get("version", "")
            if str(cache_version) == str(current_version):
                return content.get("value", {})

        try:
            content = self.get_config()
        except Exception:
            _log.warning(f"==> Failed to load remote rules: {cache_key}, return cached value if any.")
            return content.get("value", {})
        _log.info("==> Successfully loaded remote rules.")
        _log.debug(f"==> Load remote rules: {json.dumps(content, indent=2, ensure_ascii=False)}")
        if self._enable_cache and content:
            data = {"version": current_version, "value": content}
            with open(str(cache_file), "w", encoding="utf8") as f:
                f.write(json.dumps(data))
        return content
