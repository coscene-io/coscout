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
import logging.config
import shutil
import signal
import sys
import time

import click
import psutil
from kebab import KebabSource

from cos.cli.context import Context
from cos.collector import Collector, EventCodeManager
from cos.collector.mod import Mod
from cos.collector.openers import CosHandler
from cos.config import AppConfig
from cos.constant import COS_ONEFILE_PATH
from cos.core.api import ApiClient, ApiClientState, get_client
from cos.core.exceptions import DeviceNotFound, Unauthorized
from cos.core.register import Register
from cos.install.updater import Updater
from cos.mods import ModLoader
from cos.version import get_version

_log = logging.getLogger(__name__)


# noinspection PyBroadException
def run_forever(source: KebabSource, conf: AppConfig, cos_url_handler: CosHandler):
    def signal_handler(sig, _):
        print(f"\nProgram exiting gracefully by {sig}")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    cos_url_handler.set_api_client(None)
    load_mod(None, conf)
    is_first_run = True
    while True:
        try:
            if conf.logging:
                logging.config.dictConfig(conf.logging)
            Register(conf.api, conf.device_register).run()

            # check upgrade after authorized
            Updater(conf.updater).run()

            api_client = get_client(conf.api)
            cos_url_handler.set_api_client(api_client=api_client)
            if is_first_run:
                source.reload(
                    reload_interval_in_secs=conf.collector.scan_interval_in_secs,
                    skip_first=False,
                )
                is_first_run = False

            mod = load_mod(api_client, conf)
            mod.run()

            code_manager = EventCodeManager(
                conf=conf.event_code,
                convert_code=mod.convert_code,
                api_client=api_client,
            )
            Collector(conf=conf.collector, api_client=api_client, code_manager=code_manager).run()
        except DeviceNotFound:
            _log.warning("No device found, check if robot.yaml is present waiting for next scan.")
        except Unauthorized:
            _log.error(
                "Unauthorized, please check your device authorization status.",
                exc_info=True,
            )
            state = ApiClientState().load_state()
            state.authorized_device(0, "")
            state.save_state()
        except Exception:
            # 打印错误，但保证循环不被打断
            _log.error("An error occurred when running collector", exc_info=True)
        time.sleep(conf.collector.scan_interval_in_secs)


def load_mod(api_client: ApiClient | None, conf: AppConfig):
    ModLoader.load()

    mod_conf = conf.mod
    mod_name = mod_conf.name.lower()
    if "gaussian" in conf.api.server_url or "gs" == mod_name.lower():
        mod_name = "gs"

    _log.info(f"Use mod {mod_name} for collector.")
    return Mod.get_mod(mod_name)(api_client=api_client, conf=mod_conf.conf)


@click.command
@click.pass_obj
@click.option("-v", "--verbose", is_flag=True, default=False)
def daemon(ctx: Context, verbose):
    logging.getLogger().setLevel(level=logging.DEBUG if verbose else logging.INFO)
    clean_old_binary()
    _log.info(f"Starting collector daemon with {get_version()}")
    run_forever(source=ctx.source, conf=ctx.conf, cos_url_handler=ctx.cos_url_handler)


def clean_old_binary():
    current_process = psutil.Process()
    children = current_process.children(recursive=True)
    parent = current_process.ppid()
    pids = [current_process.pid] + [c.pid for c in children] + [parent]

    _log.info(f"Daemon started with pid and children pids: {pids}")
    _log.info(f"Clean old binary in {COS_ONEFILE_PATH}")
    if not COS_ONEFILE_PATH.exists():
        return
    for f in COS_ONEFILE_PATH.iterdir():
        _log.info(f"Found binary {f.name}")
        if not f.is_dir():
            continue

        should_keep = any([f"_{pid}_" in str(f.name).lower() for pid in pids])
        if not should_keep:
            shutil.rmtree(str(f.absolute()))
            _log.info(f"Cleaned old binary {f.name}")
