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
from unittest import mock

import pytest

from cos.core.api import ApiClient
from cos.core.metrics import MetricCollector, counter, gauge, timer


@pytest.fixture
def api():
    api = mock.MagicMock(spec=ApiClient)
    api.inc_counter = mock.MagicMock()
    return api


class MyClass(metaclass=MetricCollector):
    def __init__(self, api):
        self.api = api

    @counter("myclass_work_total")
    def work(self):
        # important work
        pass

    @timer("myclass_work_duration_in_secs")
    def heavy_work(self):
        time.sleep(0.01)
        pass

    @gauge("myclass_mem_usage_in_bytes")
    def mem_usage(self):
        return 1048756

    @counter("myclass_superposed_total")
    @timer("myclass_superposed_duration_in_secs")
    @gauge("myclass_superposed_mem_usage_in_bytes")
    def superposed(self):
        time.sleep(0.01)
        return 1048756


def test_metric_collector(api):
    my = MyClass(api)
    my.work()
    api.counter.assert_called()
    my.heavy_work()
    api.timer.assert_called_once()
    my.mem_usage()
    api.gauge.assert_called_once()


def test_metric_collector_superposed(api):
    my = MyClass(api)
    my.superposed()
    api.counter.assert_called_once()
    api.timer.assert_called_once()
    api.gauge.assert_called_once()
