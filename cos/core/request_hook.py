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

import requests
from pydantic import BaseModel


class NetworkUsage(BaseModel):
    download_bytes: int = 0
    upload_bytes: int = 0


network_usage = NetworkUsage(download_bytes=0, upload_bytes=0)


def response_hook(r, *args, **kwargs):
    req_length = r.request.headers.get("content-length", 0)
    res_length = r.headers.get("content-length", 0)
    network_usage.download_bytes += int(res_length)
    network_usage.upload_bytes += int(req_length)


class HookSession(requests.Session):
    def request(self, method, url, **kwargs):
        kwargs.setdefault("hooks", {"response": response_hook})
        return super().request(method, url, **kwargs)


requests.sessions.Session = HookSession


def get_network_usage():
    return network_usage.model_dump()


def get_network_upload_usage():
    return network_usage.upload_bytes


def get_network_download_usage():
    return network_usage.download_bytes


def increase_download_bytes(b: int = 0):
    network_usage.download_bytes += b


def increase_upload_bytes(b: int = 0):
    network_usage.upload_bytes += b


def reset_network_usage():
    network_usage.download_bytes = 0
    network_usage.upload_bytes = 0
