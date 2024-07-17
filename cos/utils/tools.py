# -*- coding:utf-8 -*-
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
from datetime import datetime

_log = logging.getLogger(__name__)


def size_fmt(size):
    units = ["B", "KB", "MB", "GB"]
    i = 0

    while size >= 1024 and i < len(units) - 1:
        size /= 1024
        i += 1

    return f"{size:.2f}{units[i]}"


class ProgressLogger:
    def __init__(self, file, total_size, interval=60):
        self.file = file
        self.total_size = total_size
        self.interval = interval
        self.visited = 0
        self.start_time = time.time()
        self.last_logged_time = self.start_time

    def read(self, size=None):
        chunk = self.file.read(size)
        self.visited += len(chunk)
        now = time.time()
        if now - self.last_logged_time >= self.interval:  # check every minute
            elapsed = now - self.start_time
            speed = self.visited / elapsed
            progress = (self.visited / self.total_size) * 100
            _log.info(
                f"Tranfered: {size_fmt(self.visited)}"
                f" / {size_fmt(self.total_size)}"
                f" > {progress:.2f}%"
                f" @ {size_fmt(speed)}/s"
            )
            self.last_logged_time = now
        return chunk

    def __getattr__(self, attr):
        return getattr(self.file, attr)


def iso2timestamp(iso_str: str = None) -> int:
    if not iso_str:
        iso_str = datetime.utcnow().isoformat()
    # https://note.nkmk.me/en/python-datetime-isoformat-fromisoformat/#before-python-311
    return int(datetime.fromisoformat(iso_str.replace("Z", "+00:00")).timestamp())
