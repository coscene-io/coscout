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
from collections import namedtuple
from datetime import datetime, timedelta
from functools import partial

from ruleengine.dsl.base_actions import noop_create_moment
from ruleengine.dsl.validation.config_validator import validate_config
from ruleengine.engine import Engine

from cos.core.api import ApiClient
from cos.mods.common.default.remote_rule import RemoteRule

_log = logging.getLogger(__name__)


def build_engine_from_config(configs, upload_fn=None, api_client: ApiClient = None):
    rule_list = []
    for project_rule_set_spec in configs:
        if not project_rule_set_spec.get("name", "").endswith("/diagnosisRule"):
            _log.warning("==> Found an invalid project rule set, skipping")
            continue
        project_name = project_rule_set_spec["name"].removesuffix("/diagnosisRule")
        for rule_set_spec in project_rule_set_spec["rules"]:
            if not rule_set_spec.get("enabled", False):
                continue
            validation_result, rules = validate_config(
                rule_set_spec,
                {"upload": partial(upload_fn, project_name=project_name), "create_moment": noop_create_moment},
                project_name,
            )
            if not validation_result["success"]:
                _log.error(
                    f"==> Failed to build rule for {project_name} {json.dumps(rule_set_spec, indent=2, ensure_ascii=False)} "
                    f"due to {json.dumps(validation_result, indent=2, ensure_ascii=False)}, skipping"
                )
                continue
            rule_list += rules

    device = api_client.state.load_state().device.get("name", "")

    def should_trigger_action(proj_name, rule_spec, hit):
        if not hit.get("uploadLimit", ""):
            return True

        project_rule_spec = {
            "name": f"{proj_name}/diagnosisRule",
            "rules": [
                {
                    "rules": [rule_spec],
                }
            ],
        }

        upload_limit = hit["uploadLimit"]
        if upload_limit.get("device", ""):
            try:
                device_count = api_client.count_diagnosis_rules_hit(project_rule_spec["name"], hit, device)["count"]
            except Exception:
                _log.warning(f"==> Failed to count device hit for {project_rule_spec['name']}, skipping")
                return False
            if device_count >= upload_limit["device"]["times"]:
                _log.info(
                    f"device count {device_count} reached upload limit {upload_limit['device']['times']} times, skipping"
                )
                return False

        if upload_limit.get("global", ""):
            try:
                global_count = api_client.count_diagnosis_rules_hit(project_rule_spec["name"], hit, "")["count"]
            except Exception:
                _log.warning(f"==> Failed to count global hit for {project_rule_spec['name']}, skipping")
                return False
            if global_count >= upload_limit["global"]["times"]:
                _log.info(
                    f"global count {global_count} reached upload limit {upload_limit['global']['times']} times, skipping"
                )
                return False

        return True

    def trigger_cb(proj_name, rule_spec, hit, action_triggered, _):
        project_rule_spec = {
            "name": f"{proj_name}/diagnosisRule",
            "rules": [
                {
                    "rules": [rule_spec],
                }
            ],
        }
        try:
            api_client.hit_diagnosis_rule(project_rule_spec, hit, device, action_triggered)
        except Exception:
            _log.warning(f"==> Failed to hit diagnosis rule for {project_rule_spec['name']}, skipping")
            pass

    return Engine(rule_list, should_trigger_action, trigger_cb)


class RuleExecutor:
    def __init__(self, name, api_client: ApiClient, input_stream, upload_fn):
        self.__name = name
        self.__api_client = api_client
        self.__remote_rule = RemoteRule(api_client)
        self.__input_stream = input_stream
        self.__upload_fn = upload_fn
        self.__configs = None
        self.__engine = None
        self.update_config()

    def consume_chunk(self):
        _log.info(f"==> {self.__name} consume_chunk started")
        start_time = datetime.now()
        last_item_read_time = start_time
        for item in self.__input_stream:
            # This is to avoid gap in input stream
            if datetime.now() - last_item_read_time > timedelta(seconds=30):
                self.update_config()
            self.__engine.consume_next(item)
            if datetime.now() - start_time > timedelta(minutes=1):
                self.update_config()
                start_time = datetime.now()
            last_item_read_time = datetime.now()
        _log.info(f"==> {self.__name} consume_chunk ended")

    def update_config(self):
        new_configs = self.__remote_rule.list_device_diagnosis_rules()
        if new_configs == self.__configs:
            return
        self.__configs = new_configs
        self.__engine = build_engine_from_config(self.__configs, self.__upload_fn, self.__api_client)

    def execute(self):
        self.consume_chunk()


RuleDataItem = namedtuple("RuleDataItem", "topic msg ts msgtype")
LogMessageDataItem = namedtuple("LogMessageDataItem", "message")
