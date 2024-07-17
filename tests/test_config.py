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
import os
import tempfile
from io import StringIO
from pathlib import Path
from urllib.request import BaseHandler
from urllib.response import addinfourl

import pytest

from cos.config import AppConfig, load_kebab_source


@pytest.fixture
def config_path():
    return Path(tempfile.mkdtemp()) / "config.yaml"


def test_write_as_yaml(config_path):
    result = AppConfig()
    assert result.api.server_url is not None
    result.api.server_url = "http://localhost:8000"

    result.write_as_yaml(config_path)
    assert "server_url: http://localhost:8000" in config_path.read_text()


class MockHandler(BaseHandler):
    def __init__(self, **kwargs):
        self._content = json.dumps(kwargs or {})

    def mock_open(self, req):
        return addinfourl(StringIO(self._content), [], req.get_full_url())


def test_extra_handler():
    handler = MockHandler(server_url="http://localhost:8000", project_slug="fake_org/fake_proj")
    source = load_kebab_source("mock:", extra_url_handler=handler)

    assert source.get("server_url") == "http://localhost:8000"
    assert source.get("project_slug") == "fake_org/fake_proj"


def test_env_map():
    os.environ.update({"COS_API_SERVER_URL": "http://localhost:8000"})
    os.environ.update({"COS_API_PROJECT_SLUG": "fake_org/fake_proj"})
    source = load_kebab_source()

    assert source.get("api.server_url") == "http://localhost:8000"
    assert source.get("api.project_slug") == "fake_org/fake_proj"
