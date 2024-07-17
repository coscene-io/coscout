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
import time
from functools import wraps

_log = logging.getLogger(__name__)


class MetricDefinition:
    def __init__(self, metric_name, metric_type, description, labels):
        self.metric_name = metric_name
        self.metric_type = metric_type
        self.description = description
        self.labels = labels or {}


def __define_metric(metric_name, metric_type, description, labels):
    def decorator(func):
        new_metric = MetricDefinition(metric_name, metric_type, description, labels)
        if hasattr(func, "metrics"):
            func.metrics.append(new_metric)
        else:
            func.metrics = [new_metric]
        return func

    return decorator


def counter(metric_name, description=None, labels=None):
    return __define_metric(metric_name, "counter", description, labels)


def timer(metric_name, description=None, labels=None):
    return __define_metric(metric_name, "timer", description, labels)


def gauge(metric_name, description=None, labels=None):
    return __define_metric(metric_name, "gauge", description, labels)


class MetricCollector(type):
    def __new__(mcs, name, bases, attrs):
        original_init = attrs.get("__init__")

        @wraps(original_init)
        def new_init(self, api, *args, **kwargs):
            original_init(self, api, *args, **kwargs)

            for attr_name, attr_value in attrs.items():
                if hasattr(attr_value, "metrics") and isinstance(attr_value.metrics, list):
                    new_func = attr_value
                    for metric in attr_value.metrics:
                        if not isinstance(metric, MetricDefinition):
                            _log.warning("Metric %s is not instance of MetricDefinition", metric)
                            continue
                        new_func = mcs._wrap(new_func, api, metric)
                    setattr(self, attr_name, new_func.__get__(self, type(self)))

        attrs["__init__"] = new_init
        return super().__new__(mcs, name, bases, attrs)

    @staticmethod
    def _wrap(func, api, metric: MetricDefinition):
        @wraps(func)
        def _counter(self, *args, **kwargs):
            result = func(self, *args, **kwargs)
            api.counter(metric.metric_name, description=metric.description, labels=metric.labels)
            return result

        @wraps(func)
        def _timer(self, *args, **kwargs):
            start = time.time()
            result = func(self, *args, **kwargs)
            api.timer(
                metric.metric_name,
                time.time() - start,
                metric.description,
                metric.labels,
            )
            return result

        @wraps(func)
        def _gauge(self, *args, **kwargs):
            result = func(self, *args, **kwargs)
            if result is not None and isinstance(result, (int, float)):
                api.gauge(metric.metric_name, result, metric.description, metric.labels)
                pass
            else:
                _log.error(
                    "Gauge metric %s should return int or float, got %s",
                    metric.metric_name,
                    result,
                )
            return result

        @wraps(func)
        def _unknown(self, *args, **kwargs):
            _log.error("Unknown metric type: %s", metric.metric_type)
            return func(self, *args, **kwargs)

        return {
            "counter": _counter,
            "timer": _timer,
            "gauge": _gauge,
        }.get(metric.metric_type, _unknown)
