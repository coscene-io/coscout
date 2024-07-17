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
import re
from io import StringIO
from urllib.request import BaseHandler, Request
from urllib.response import addinfourl

from cos.collector.remote_config import RemoteConfig
from cos.core.api import ApiClient

_log = logging.getLogger(__name__)


class CosHandler(BaseHandler, RemoteConfig):
    path_pattern = r"^(?P<resource>[\w+/\-]+)/configMaps/(?P<path>.*)$"

    def __init__(self, api_client: ApiClient = None, enable_cache: bool = True):
        self.api_client = api_client
        self.enable_cache = enable_cache
        self._config_full_path = None

        super().__init__(enable_cache=enable_cache)

    def set_api_client(self, api_client: ApiClient | None):
        self.api_client = api_client

    @staticmethod
    def parse_path(path: str):
        match = re.match(CosHandler.path_pattern, path)
        if match:
            parent_name = match.group("resource")
            config_key = match.group("path")
            return parent_name, config_key
        else:
            raise ValueError(f"invalid config path: {path}")

    def get_cache_key(self):
        return self._config_full_path

    def get_config_version(self):
        parent_name, config_key = self.parse_path(self._config_full_path)
        return self.api_client.get_configmap_metadata(config_key=config_key, parent_name=parent_name).get("currentVersion", -1)

    def get_config(self):
        parent_name, config_key = self.parse_path(self._config_full_path)
        return self.api_client.get_configmap(config_key=config_key, parent_name=parent_name).get("value", {})

    def cos_open(self, req: Request):
        self._config_full_path = req.get_full_url()[len(req.type + ":") :].lstrip("/")
        if self.api_client is None:
            _log.debug(f"api client is not set, skip cos schema url: {req.get_full_url()}")
            return addinfourl(StringIO("{}"), [], req.get_full_url())

        content = super().read_config()
        return addinfourl(StringIO(json.dumps(content)), [], req.get_full_url())
