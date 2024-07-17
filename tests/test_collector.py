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
from cos.collector.collector import Collector, CollectorConfig
from cos.core.models import RecordCache


@pytest.fixture
def code_json_path(tmp_path_factory):
    code_json_path = tmp_path_factory.mktemp("state") / "code.json"
    code_json_path.write_text(
        json.dumps(
            {
                "20063": "机器人任务中停留原地己超过5分钟",
                "13065": "左线激光数据异常",
                "21001": "防撞条触发，请注意周边环境",
            },
            indent=4,
            sort_keys=True,
        )
    )
    yield code_json_path
    # Cleanup: delete the temporary file
    if code_json_path.exists():
        code_json_path.unlink()


@pytest.fixture
def api():
    return mock.MagicMock()


@pytest.fixture
def collector(api, code_json_path):
    up_conf = CollectorConfig(delete_after_upload=False)

    code_conf = EventCodeConfig(enabled=False, code_json_url=str(code_json_path))

    return Collector(
        up_conf,
        api_client=api,
        code_manager=EventCodeManager(code_conf, api_client=api),
    )


def test_handle_record_collected(collector, api):
    collector.handle_record(RecordCache(event_code="20063", timestamp=0, skipped=True))
    api.assert_not_called()
