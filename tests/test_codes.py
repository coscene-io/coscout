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
from unittest import mock

import pytest

from cos.collector.codes import EventCodeConfig, EventCodeManager


@pytest.fixture
def state_path(tmp_path_factory):
    state_path = tmp_path_factory.mktemp("state") / "code_limit.state.json"
    yield state_path
    # Cleanup: delete the temporary file
    if state_path.exists():
        state_path.unlink()


@pytest.fixture
def code_json_path(tmp_path_factory):
    code_json_path = tmp_path_factory.mktemp("state") / "code.json"
    code_json_path.write_text(
        json.dumps(
            {"200": "OK", "404": "Not Found", "500": "Server Error"},
            indent=4,
            sort_keys=True,
        )
    )
    yield code_json_path
    # Cleanup: delete the temporary file
    if code_json_path.exists():
        code_json_path.unlink()


@pytest.fixture
def code_mgr(state_path, code_json_path):
    mock_api = mock.MagicMock()
    conf = EventCodeConfig(
        enabled=True,
        whitelist={"200": 2, "404": -1, "500": 2},
        code_json_url=str(code_json_path),
    )
    return EventCodeManager(conf, api_client=mock_api, state_path=str(state_path))


def test_hit(code_mgr, state_path):
    code_mgr.hit(200)
    code_mgr.hit(200)
    code_mgr.hit(404)

    with state_path.open() as f:
        state = json.load(f)
        assert "counters" in state
        counters = state["counters"]
        assert counters["200"] == 2
        assert counters["404"] == 1
        assert "500" not in counters


def test_is_over_limit(code_mgr):
    code_mgr.hit(200)
    code_mgr.hit(200)
    code_mgr.hit(200)
    code_mgr.hit(404)

    assert code_mgr.is_over_limit(200)
    assert not code_mgr.is_over_limit(404)
    assert not code_mgr.is_over_limit(500)


def test_reset(code_mgr, state_path):
    code_mgr.hit(200)
    code_mgr.hit(200)
    code_mgr.hit(200)
    code_mgr.hit(404)

    state_path.write_text(json.dumps({"last_reset_timestamp": 0}, indent=4, sort_keys=True))

    assert not code_mgr.is_over_limit(200)
    assert not code_mgr.is_over_limit(404)
    assert not code_mgr.is_over_limit(500)


def test_get_message(code_mgr):
    assert code_mgr.get_message(200) == "OK"
    assert code_mgr.get_message(404) == "Not Found"
    assert code_mgr.get_message(500) == "Server Error"
    assert code_mgr.get_message(999) == "Unknown Error"
