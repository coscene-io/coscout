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

import platform
from pathlib import Path

import platformdirs

__COMPANY_NAME = "coscene"
__APP_NAME = "cos"


def is_windows():
    return platform.system().lower() == "windows"


def __get_config_path():
    if is_windows():
        return Path(
            platformdirs.site_config_path(appname=__APP_NAME, appauthor=__COMPANY_NAME),
            "config",
            "config.yaml",
        )
    return Path(platformdirs.user_config_dir(appname=__APP_NAME), "config.yaml")


def __get_cache_path():
    if is_windows():
        return Path(platformdirs.site_cache_dir(appname=__APP_NAME, appauthor=__COMPANY_NAME))
    return Path(platformdirs.user_cache_dir(appname=__APP_NAME))


def __get_state_path():
    if is_windows():
        return Path(
            platformdirs.site_data_dir(appname=__APP_NAME, appauthor=__COMPANY_NAME),
            "state",
        )
    return Path(platformdirs.user_state_dir(appname=__APP_NAME))


def __get_onefile_path():
    if is_windows():
        return Path(platformdirs.site_cache_dir(appauthor=__COMPANY_NAME))
    return Path(platformdirs.user_cache_dir(appname=__COMPANY_NAME))


COS_DEFAULT_CONFIG_PATH = __get_config_path()
COS_CACHE_PATH: Path = Path(__get_cache_path())
COS_ONEFILE_PATH: Path = Path(__get_onefile_path())
CODE_JSON_CACHE_PATH: Path = Path(__get_cache_path()) / "code.json"

COS_STATE_PATH: Path = Path(__get_state_path())
CODE_LIMIT_STATE_PATH: Path = COS_STATE_PATH / "code_limit.state.json"
API_CLIENT_STATE_PATH: Path = COS_STATE_PATH / "api_client.state.json"
INSTALL_STATE_PATH: Path = COS_STATE_PATH / "install.state.json"
RAW_DEVICE_STATE_PATH: Path = COS_STATE_PATH / "raw_device.state.json"
FILE_STATE_PATH: Path = COS_STATE_PATH / "file.state.json"

RECORD_DIR_PATH: Path = COS_STATE_PATH / "records"
RECORD_STATE_RELATIVE_PATH: str = str(Path(".cos", "state.json"))
BIN_DIR_PATH: Path = COS_STATE_PATH / "bin"
UPDATER_STATE_PATH: Path = COS_STATE_PATH / "updater.state.json"

LOGGING_FORMAT = "%(asctime)s %(levelname).7s [%(filename)s:%(lineno)d | %(funcName)s] - %(message)s"
