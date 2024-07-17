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
import os
from importlib import util
from pathlib import Path

import cos.mods.common  # noqa
import cos.mods.private  # noqa


# Small utility to automatically load modules
def load_module(module_path: str):
    name = os.path.split(module_path)[-1]
    spec = util.spec_from_file_location(name, module_path)
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_log = logging.getLogger(__name__)


class ModLoader:
    _is_loaded = False

    @staticmethod
    def load():
        if ModLoader._is_loaded:
            return

        _log.info("Loading mod modules...")

        # Get current path
        path = os.path.abspath(__file__)
        dir_path = Path(path).parent

        for fname in dir_path.rglob("**/*.py"):
            # Load only "real modules"
            if not fname.name.startswith(".") and not fname.name.startswith("__") and fname.name.endswith("mod.py"):
                try:
                    load_module(str(fname.absolute()))
                    ModLoader._is_loaded = True
                except Exception:
                    _log.error(f"Failed to load module: {fname}", exc_info=True)
