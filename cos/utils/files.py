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
import logging
import os
import shutil
from pathlib import Path

_log = logging.getLogger(__name__)


class LimitedFileReader:
    def __init__(self, file, limit):
        self.file = file
        self.limit = limit
        self.total_read = 0

    def read(self, size=-1):
        if self.total_read >= self.limit:
            return b""
        if size < 0:
            size = self.limit
        size = min(size, self.limit - self.total_read)
        data = self.file.read(size)
        self.total_read += len(data)
        return data


def sha256_file(filepath: Path, size: int = -1, block_size: int = 4096):
    # sha256 only up to the recorded size (not the whole file)
    # this is helpful when the file is still being appended, but we'd like to freeze the state
    count_down = size
    sha256_hash = hashlib.sha256()
    with filepath.open("rb") as f:
        for byte_block in iter(lambda: f.read(block_size), b""):
            if 0 < count_down < len(byte_block):
                byte_block = byte_block[:count_down]
            sha256_hash.update(byte_block)
            if size >= 0:
                count_down -= len(byte_block)
                if count_down <= 0:
                    break
    return sha256_hash.hexdigest()


def hardlink_recursively(source_dirs, dest_dir):
    """
    Recursively hard links all files in the source directories to the destination directory.

    :param source_dirs: A list of source directories to link from.
    :param dest_dir: The destination directory to link to.
    :return: A list of hard links created.
    """
    hardlinks = []

    if isinstance(source_dirs, str):
        source_dirs = [source_dirs]

    dest_path = Path(dest_dir)
    for p in source_dirs:
        source_path = Path(p)
        if source_path.is_file():
            link = hardlink(source_path, dest_path / source_path.name)
            hardlinks.append(str(link))
        else:
            for entry in source_path.glob("**/*"):
                if entry.is_file():
                    link = hardlink(entry, dest_path / entry.relative_to(source_path))
                    hardlinks.append(str(link))
    return hardlinks


def hardlink(target_path: Path, link_path: Path):
    if target_path.is_file():
        if not link_path.is_file():
            link_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(str(target_path), str(link_path))
            except OSError:
                shutil.copy(str(target_path), str(link_path))
        else:
            _log.warning(f"File {link_path} already exists, skip.")
    return link_path


def is_image(filename: str):
    return filename.endswith((".jpg", ".jpeg", ".png"))
