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

import pytest
from pydantic import ValidationError

from cos.core.models import FileInfo, RecordCache


def test_cache(tmp_path):
    rc = RecordCache(
        event_code="test",
        timestamp=1234567890 * 1000,
        files=["non-exists.txt", "non-exists.txt", "non-exists.txt"],
    )
    assert rc.key == "test_2009-02-13-23-31-30_0"
    assert set(rc.files) == {"non-exists.txt"}

    def _tmp(*filenames):
        file_list = []
        for f in filenames:
            filepath = tmp_path / f
            file_list.append(str(filepath))
            filepath.write_text("random")
        return file_list

    files_with_duplicates = _tmp("first.txt", "same.txt", "same.txt")

    with pytest.raises(ValidationError):
        RecordCache(files=files_with_duplicates)

    rc = RecordCache(event_code="test", timestamp=1234567890 * 1000, files=files_with_duplicates)

    assert rc.key == "test_2009-02-13-23-31-30_0"
    assert set(rc.files) == {files_with_duplicates[0], files_with_duplicates[1]}


def _assert_file_info(file_info, filepath, content, filename=None, sized=True, hashed=True):
    size = len(content) if sized else None
    sha256 = hashlib.sha256(content.encode()).hexdigest() if hashed else None

    assert file_info.filepath == filepath
    assert file_info.filename == filename or filepath.name
    if sized:
        assert file_info.size == size
    else:
        assert file_info.size is None
    if hashed:
        assert file_info.sha256 == sha256
    else:
        assert file_info.sha256 is None
    assert file_info.dict() == {
        "filepath": str(filepath),
        "filename": filename or filepath.name,
        "size": size,
        "sha256": sha256,
        "name": "/files/" + (filename or filepath.name),
    }
    with file_info.filepath.open() as fp:
        assert fp.read(file_info.size) == content


def test_file_info(tmp_path):
    filepath = tmp_path / "test.txt"
    content = "local"
    filepath.write_text(content)
    file_info = FileInfo(filepath=filepath)

    # default hash is not inplace
    new_file_info = file_info.complete()
    assert new_file_info != file_info
    _assert_file_info(file_info, filepath, content, sized=False, hashed=False)  # original object not hashed
    _assert_file_info(new_file_info, filepath, content)  # new object hashed

    # when inplace the return value is the original file_info, and hashed.
    new_file_info = file_info.complete(inplace=True)
    assert new_file_info == file_info
    _assert_file_info(file_info, filepath, content)

    # rewrite the file
    new_content = "local & global"
    filepath.write_text(new_content)
    new_file_info = file_info.complete()
    _assert_file_info(new_file_info, filepath, content)  # read up to the original size, so it behaves the same

    # forced_rehash hashed with the new value
    new_file_info = file_info.complete(force_rehash=True)
    _assert_file_info(new_file_info, filepath, new_content)


def test_file_info_customized_values(tmp_path):
    filepath = tmp_path / "test.txt"
    content = "local & global"
    filepath.write_text(content)
    file_info = FileInfo(filepath=str(filepath), filename="result/test.txt", size=5)
    _assert_file_info(file_info, filepath, content[:5], filename="result/test.txt", hashed=False)

    file_info.complete(inplace=True)
    _assert_file_info(file_info, filepath, content[:5], filename="result/test.txt")


def test_file_info_non_exist_file(tmp_path):
    # the file is missing, but the file_info is still valid
    file_info = FileInfo(filepath="test.txt")

    with pytest.raises(FileNotFoundError):
        file_info.complete()
