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

import sys
import time

import pytest

from cos.constant import RECORD_STATE_RELATIVE_PATH
from cos.core.models import RecordCache


@pytest.fixture
def state_path(tmp_path_factory):
    state_path = tmp_path_factory.mktemp("state") / "state.json"
    yield state_path
    # Cleanup: delete the temporary file
    if state_path.exists():
        state_path.unlink()


def test_save_load(state_path):
    s1 = RecordCache(event_code="11111", timestamp=int(time.time())).save_state(state_path)
    s2 = RecordCache(event_code="22222", timestamp=int(time.time())).load_state(state_path)
    assert s1.event_code == s2.event_code
    assert s1.timestamp == s2.timestamp
    s3 = RecordCache.load_state_from_disk(state_path)
    assert s1.event_code == s3.event_code
    assert s1.timestamp == s3.timestamp
    sep = "\\" if sys.platform.startswith("win") else "/"
    assert str(s1.state_path).endswith(f"{s1.key}{sep}{RECORD_STATE_RELATIVE_PATH}")
