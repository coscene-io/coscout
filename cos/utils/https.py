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
from datetime import datetime
from pathlib import Path

import requests

_log = logging.getLogger(__name__)


def download_if_modified(url, filename=None, last_modified=None):
    headers = {}
    # Check if the resource file exists and get its last modified date
    if not last_modified and filename and os.path.exists(filename):
        last_modified = datetime.fromtimestamp(os.path.getmtime(filename))
    if last_modified:
        headers["If-Modified-Since"] = last_modified.strftime("%a, %d %b %Y %H:%M:%S GMT")
    response = requests.get(url, headers=headers, timeout=30)
    # If the server returned a 304 Not Modified response, the file hasn't changed
    if response.status_code == 304:
        _log.debug("The {filename} hasn't changed since the last download.")
        if filename and Path(filename).is_file():
            with open(filename, "rb") as f:
                return f.read()
        else:
            return None
    else:
        if filename and Path(filename).is_file():
            with open(filename, "wb") as f:
                f.write(response.content)
        # Otherwise, download the updated resource and save it to a file
        return response.content


def download_file(url: str, filename: str):
    with requests.get(url, stream=True, allow_redirects=True, timeout=60 * 5) as r:
        r.raise_for_status()
        _log.info(f"saving {url} to {filename}")
        with open(filename, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 512):
                f.write(chunk)
    _log.info(f"downloaded {url} to {filename}")
