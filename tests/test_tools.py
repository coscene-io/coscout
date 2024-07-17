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

import hashlib
from datetime import datetime
from pathlib import Path

import pytest
import requests_mock

from cos.utils import LimitedFileReader, download_if_modified, hardlink_recursively, sha256_file, size_fmt

url = "http://fake.address/"


@pytest.fixture
def mock_req():
    def request_callback(request, context):
        if "If-Modified-Since" in request.headers:
            context.status_code = 304
            return None
        else:
            context.status_code = 200
            return "remote"

    with requests_mock.Mocker() as m:
        m.get(url, text=request_callback)
        yield m


def test_download_if_modified_with_local_file(mock_req, tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text("local")
    assert download_if_modified(url, str(state_path)).decode() == "local"
    assert download_if_modified(url, last_modified=datetime.now()) is None
    assert download_if_modified(url).decode() == "remote"


def test_recursive_hardlink(tmp_path):
    # Create some directories and files in the source directory
    src_path = tmp_path / "source"
    dst_path = tmp_path / "dest"
    (src_path / "subdir").mkdir(parents=True, exist_ok=True)

    (src_path / "file1.txt").write_text("Hello, world!")
    (src_path / "subdir/file2.txt").write_text("Hello again!")

    # Run the recursive_hardlink function
    links = hardlink_recursively(str(tmp_path / "source"), str(dst_path))
    link_paths = [Path(p) for p in links]
    assert link_paths == [dst_path / "file1.txt", dst_path / "subdir/file2.txt"]

    assert link_paths[0].read_text() == "Hello, world!"
    assert link_paths[1].read_text() == "Hello again!"

    assert link_paths[0].stat().st_ino == (src_path / "file1.txt").stat().st_ino
    assert link_paths[1].stat().st_ino == (src_path / "subdir/file2.txt").stat().st_ino


def test_sha256(tmp_path):
    content = "Hello, world!"
    file = tmp_path / "file1.txt"
    file.write_text(content)
    size = file.stat().st_size
    hash_str = hashlib.sha256(content.encode()).hexdigest()

    assert sha256_file(file) == hash_str
    assert sha256_file(file, size) == hash_str
    with open(file, "a+") as f:
        f.write("Hello, world!1234")
    assert sha256_file(file, size) == hash_str


def test_limit_reader(tmp_path):
    content = "Hello, world!"
    file = tmp_path / "file1.txt"
    file.write_text(content)
    size = file.stat().st_size

    with file.open() as f:
        limit_reader = LimitedFileReader(f, size)
        assert limit_reader.read(size + 10) == content
        assert limit_reader.read(1) == b""

    with open(file, "a+") as f:
        f.write("Hello, world!1234")
    with file.open() as f:
        limit_reader = LimitedFileReader(f, size)
        assert limit_reader.read(size - 1) == content[:-1]
        assert limit_reader.read(1) == content[-1:]
        assert limit_reader.read(1) == b""
        assert limit_reader.read(1) == b""


def test_size_fmt():
    assert size_fmt(1) == "1.00B"
    assert size_fmt(1024) == "1.00KB"
    assert size_fmt(1024**2) == "1.00MB"
    assert size_fmt(1024**3) == "1.00GB"
    assert size_fmt(1024**4) == "1024.00GB"
