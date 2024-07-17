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

import time
from unittest.mock import Mock
from urllib.request import build_opener

import pytest
from kebab import UrlSource

from cos.collector.openers import CosHandler
from cos.core.api import ApiClient

test_cases = [
    (
        "organizations/cf746e23-3210-4b8f-bdfa-fb771d1ac87c",
        "invalid_uuid/8d789d97-4679-4be3-a9e-2b169e2348f9/myapp/myconfig.json",
    ),
    (
        "organizations/current",
        "invalid_uuid/8d789d97-4679-4be3-a9e-2b169e2348f9/myapp/myconfig.json",
    ),
    (
        "warehouses/4fae6133-2653-4b85-a15e-5435c158f44f/projects/889b4753-9912-4b91-b97a-35c64f459356",
        "myapp/myconfig.json",
    ),
]


@pytest.mark.parametrize("parent_name,config_key", test_cases)
def test_parse_url(parent_name, config_key):
    assert (parent_name, config_key) == CosHandler.parse_path(f"{parent_name}/configMaps/{config_key}")


@pytest.fixture
def mock_api_client():
    return Mock(ApiClient)


@pytest.mark.parametrize("parent_name,config_key", test_cases)
def test_open(mock_api_client, parent_name, config_key):
    mock_api_client.get_configmap.return_value = {"value": {"score": 100}}

    source = UrlSource(
        f"cos://{parent_name}/configMaps/{config_key}",
        opener=build_opener(CosHandler(mock_api_client, enable_cache=False)),
    )

    assert source.get("score") == 100
    mock_api_client.get_configmap.assert_called_with(config_key=config_key, parent_name=parent_name)


@pytest.mark.parametrize(
    "parent_name,config_key",
    [
        ("devices/cf746e23-3210-4b8f-bdfa-fb771d1ac87c", "myapp/myconfig.json"),
        ("organizations/current", "myapp/myconfig.json"),
    ],
)
def test_open_without_api_key(mock_api_client, parent_name, config_key):
    mock_api_client.get_configmap.return_value = {"value": {"score": 100}}
    cos_handler = CosHandler(enable_cache=False)
    source = UrlSource(
        f"cos://{parent_name}/configMaps/{config_key}",
        opener=build_opener(cos_handler),
    ).reload(reload_interval_in_secs=0.001, skip_first=True)

    assert source.get("score") is None
    mock_api_client.get_configmap.assert_not_called()

    cos_handler.set_api_client(mock_api_client)
    time.sleep(0.1)

    assert source.get("score") == 100
    mock_api_client.get_configmap.assert_called_with(config_key=config_key, parent_name=parent_name)
