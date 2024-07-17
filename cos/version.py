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
from pathlib import Path
from subprocess import STDOUT

_log = logging.getLogger(__name__)


def get_version():
    try:
        # noinspection PyUnresolvedReferences
        from cos.__version__ import __version__

        return __version__
    except ImportError:
        import subprocess

        try:
            return (
                subprocess.check_output(
                    ["git", "describe", "--always", "--tags"],
                    cwd=Path(__file__).parent,
                    stderr=STDOUT,
                )
                .decode()
                .strip()
            )
        except subprocess.CalledProcessError:
            return None
