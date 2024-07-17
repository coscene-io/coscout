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
import click

from cos.cli.context import Context
from cos.core.exceptions import CosException

_log = logging.getLogger(__name__)


@click.group
def remote_config():
    pass


@remote_config.command
@click.pass_obj
def rules(ctx: Context):
    api_state = ctx.api.state.load_state()
    if api_state.device is None:
        raise CosException("device is none")

    device_name = api_state.device.get("name", None)
    if device_name is None:
        raise CosException("device_name is none")

    projects = ctx.api.list_device_projects(device_name=device_name)
    project_names = [p.get("name") for p in projects]

    device_rules = []
    for proj_name in project_names:
        device_rules.append(
            {
                "project_name": proj_name,
                "version": ctx.api.get_diagnosis_rules_metadata(proj_name).get("currentVersion", -1),
                "rules": [ctx.api.get_diagnosis_rule(proj_name)],
            }
        )
    click.echo(json.dumps(device_rules))
