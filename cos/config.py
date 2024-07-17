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

import logging
from pathlib import Path
from urllib.request import BaseHandler

from kebab import KebabSource, load_source
from pydantic import BaseModel

from cos.collector import CollectorConfig, EventCodeConfig
from cos.collector.mod import ModConfig
from cos.constant import COS_DEFAULT_CONFIG_PATH
from cos.core.api import ApiClientConfig
from cos.core.register import RegisterConfig
from cos.install.updater import UpdaterConfig
from cos.utils.yaml import dump

_log = logging.getLogger(__name__)


class AppConfig(BaseModel):
    logging: dict = {}
    api: ApiClientConfig = ApiClientConfig()
    collector: CollectorConfig = CollectorConfig()
    event_code: EventCodeConfig = EventCodeConfig()
    updater: UpdaterConfig = UpdaterConfig()
    device_register: RegisterConfig = RegisterConfig()
    mod: ModConfig = ModConfig()

    def write_as_yaml(self, file_path: Path = None, exclude_defaults: bool = False):
        if file_path is None:
            file_path = COS_DEFAULT_CONFIG_PATH
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with file_path.open("w+", encoding="utf8") as f:
            f.write(dump(self.model_dump(exclude_defaults=False)))


def load_kebab_source(config_file_from_commandline: str = None, extra_url_handler: BaseHandler = None) -> KebabSource:
    return load_source(
        [config_file_from_commandline or str(COS_DEFAULT_CONFIG_PATH)],
        fallback_dict={},
        extra_handlers=[extra_url_handler],
        env_var_map={
            "COS_API_SERVER_URL": "api.server_url",
            "COS_API_PROJECT_SLUG": "api.project_slug",
        },
    )
