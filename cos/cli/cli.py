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

import logging.config
import sys

import click
from pydantic import ValidationError

from cos.cli import collector, remote_config
from cos.cli.context import Context
from cos.collector.openers import CosHandler
from cos.config import AppConfig, load_kebab_source
from cos.core.api import ApiClientState, get_client
from cos.version import get_version

_log = logging.getLogger(__name__)


def print_version(ctx, param, value):
    if not value or ctx.resilient_parsing:
        return
    version = get_version() or "unknown"
    click.echo(version)
    ctx.exit()


@click.group
@click.option("-c", "--config-file", type=str, default=None)
@click.option("-v", "--verbose", is_flag=True, default=False)
@click.option("--version", is_flag=True, callback=print_version, expose_value=False, is_eager=True)
@click.pass_context
def cli(ctx, config_file, verbose):
    logging.getLogger().setLevel(level=logging.DEBUG if verbose else logging.INFO)
    try:
        cos_url_handler = CosHandler()
        source = load_kebab_source(config_file, extra_url_handler=cos_url_handler)

        conf = source.get(expected_type=AppConfig, update_after_reload=True)
        api = get_client(conf.api)
        cos_url_handler.set_api_client(api)

        if ApiClientState().load_state().is_authed():
            source.reload(
                reload_interval_in_secs=conf.collector.scan_interval_in_secs,
                skip_first=False,
            )
        else:
            source.reload(
                reload_interval_in_secs=conf.collector.scan_interval_in_secs,
                skip_first=True,
            )
    except ValidationError:
        _log.error("配置文件错误, server_url, project_slug 为必填项", exc_info=True)
        sys.exit(1)
    ctx.obj = Context(source=source, conf=conf, api=api, cos_url_handler=cos_url_handler)


cli.add_command(collector.daemon)
cli.add_command(remote_config.remote_config)
