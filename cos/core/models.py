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

import datetime
import json
import logging
import os
import shutil
import time
from abc import ABCMeta, abstractmethod
from pathlib import Path, PosixPath
from typing import Any, Dict, List

from pydantic import BaseModel, field_serializer, field_validator, model_validator
from pydantic_core import ValidationError

from cos.constant import RAW_DEVICE_STATE_PATH, RECORD_DIR_PATH, RECORD_STATE_RELATIVE_PATH
from cos.utils import sha256_file

_log = logging.getLogger(__name__)


class FileInfo(BaseModel):
    filepath: Path
    filename: str | None = None
    size: int | None = None
    sha256: str | None = None

    @field_serializer("filepath")
    def serialize_dt(self, filepath: Path, _info):
        return str(filepath)

    @field_validator("filepath", mode="before")
    def filepath_to_path(cls, v):
        if isinstance(v, str):
            return Path(v)
        return v

    @model_validator(mode="after")
    def set_filename(self) -> "FileInfo":
        if self.filepath and self.filename is None:
            self.filename = self.filepath.name
        return self

    def dict(self, record_name: str = "", *args, **kwargs):
        result = super().model_dump(*args, **kwargs)
        result["filepath"] = str(result["filepath"])
        result["name"] = record_name + "/files/" + result["filename"]
        return result

    @property
    def is_changed(self, only_original_size=False):
        return self.size != self.filepath.stat().st_size or self.sha256 != sha256_file(
            self.filepath, self.size if only_original_size else -1
        )

    @property
    def is_completed(self):
        return self.filepath and self.filename and self.sha256 and self.size

    def complete(self, force_rehash=False, inplace=False, skip_sha256=False, block_size=4096):
        """
        CAVEATS: This class handles files that may grow over time, assuming the original segment remains
        unchanged. To ensure consistency, always update SHA-256 after size hash must occur atomically,
        avoiding potential synchronization issues.

        :param block_size: 每次读取的 block 大小
        :param force_rehash: 是否强制重新计算 size 和 sha256
        :param inplace: 是否在原对象上修改
        :return: 最终文件名，sha256，大小以及输入的路径组成的新的 FileInfo 对象
        """
        # refill filename
        filename = self.filename or self.filepath.name
        if not self.filepath.is_file():
            raise FileNotFoundError(f"File {self.filepath} not found")

        # refill size
        size = self.size
        if not self.size or force_rehash:
            size = self.filepath.stat().st_size

        # refill sha256
        sha256 = self.sha256
        if not skip_sha256 and (not sha256 or force_rehash):
            _log.debug(f"==> Calculating file sha256 for {self.filepath}")
            sha256 = sha256_file(self.filepath, size, block_size)

        if inplace:
            self.filename = filename
            self.size = size
            self.sha256 = sha256
            return self
        return FileInfo(filepath=self.filepath, filename=filename, sha256=sha256, size=size)


class BaseState(BaseModel, metaclass=ABCMeta):
    @abstractmethod
    def state_path(self) -> Path:
        pass

    def save_state(self, state_path: Path = None):
        state_path = state_path or self.state_path
        state_path.parent.mkdir(parents=True, exist_ok=True)
        with state_path.open("w") as fp:
            json.dump(self.model_dump(), fp, indent=2, cls=self.CosJsonEncoder)
        _log.debug(f"==> Save state to {state_path}")
        return self

    def load_state(self, state_path: Path = None):
        state_path = state_path or self.state_path
        if state_path.exists():
            with state_path.open("r") as fp:
                self.__dict__.update(json.load(fp))
        _log.debug(f"==> Load state from {state_path}")
        return self

    class CosJsonEncoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, PosixPath):
                return str(obj)
            return super().default(obj)


class Task(BaseModel):
    title: str = ""
    description: str = ""
    record_name: str = ""
    assignee: str | None = None


class Moment(BaseModel):
    """
    moment struct.
    """

    title: str = ""
    description: str = ""
    # milliseconds since epoch
    timestamp: int
    # milliseconds
    duration: int = 0
    metadata: Dict[str, str] = {}
    task: Task = Task()


class RecordCache(BaseState):
    """
    each record is saved at:
        f"{RECORD_DIR_PATH}/{record_key}/{RECORD_STATE_RELATIVE_PATH}"
    where record_key is a unique key looks like:
        f"{%Y-%m-%d-%H-%M-%S}_{milliseconds}"
    """

    uploaded: bool = False
    skipped: bool = False
    event_code: str | None = None
    project_name: str | None = None

    # milliseconds since epoch
    timestamp: int
    labels: List[str] = []
    record: dict = {}
    moments: List[Moment] = []

    # task
    task: dict = {}

    # the original files (might be copied from file_infos)
    files: List[str] = []
    # the files with extra info such as size and sha256 (might be hardlink files)
    file_infos: List[FileInfo] = []
    # the source paths to be deleted along with the record, usually the original file directory
    paths_to_delete: List[str] = []

    def __init__(self, **data: Any):
        super().__init__(**data)

        # file_info has higher priority
        if not self.files:
            self.files = [str(f.filepath) for f in self.file_infos]
        elif not self.file_infos:
            self.file_infos = [FileInfo(filepath=f) for f in self.files]

    @property
    def key(self):
        seconds = self.timestamp // 1000
        milliseconds = self.timestamp % 1000
        dt = datetime.datetime.fromtimestamp(seconds, datetime.timezone.utc).strftime("%Y-%m-%d-%H-%M-%S")

        if self.event_code:
            return f"{self.event_code}_{dt}_{milliseconds}"
        return f"{dt}_{milliseconds}"

    @property
    def state_path(self):
        return self.base_dir_path / RECORD_STATE_RELATIVE_PATH

    @property
    def base_dir_path(self):
        return RECORD_DIR_PATH / self.key

    @staticmethod
    def load_state_from_disk(file_path: Path):
        with file_path.open("r") as fp:
            return RecordCache.model_validate(json.load(fp))

    def delete_cache_dir(self, delay_in_hours=0):
        if delay_in_hours >= 0 and time.time() - self.timestamp / 1000 > delay_in_hours * 3600:
            if self.base_dir_path.exists():
                shutil.rmtree(str(self.base_dir_path.absolute()))
            _log.info(f"==> State file and folder expired and deleted: {self.key}")

            for path_str in self.paths_to_delete:
                p = Path(path_str).absolute()
                if not p.exists():
                    _log.warning(f"==> Source path not found: {path_str}")
                    continue
                try:
                    if p.is_dir():
                        shutil.rmtree(str(p))
                    else:
                        os.remove(str(p))
                except Exception:
                    _log.error(f"==> Error when deleting source path: {path_str}", exc_info=True)

    def list_files(self):
        return [str(f) for f in self.base_dir_path.glob("**/*") if f.is_file() and ".cos" not in f.parts]

    @staticmethod
    def find_all(target_dir_path: Path = RECORD_DIR_PATH):
        """
        find all records from RECORD_DIR_PATH
        """
        target_dir_path.mkdir(parents=True, exist_ok=True)
        for dir_path in target_dir_path.iterdir():
            if dir_path.is_dir():
                file_path = dir_path / RECORD_STATE_RELATIVE_PATH
                if file_path.exists():
                    try:
                        yield RecordCache.load_state_from_disk(file_path)
                    except ValidationError:
                        _log.warning(f"==> Invalid record state file: {file_path}, delete it")
                        shutil.rmtree(str(dir_path.absolute()))
                        _log.info(f"==> Invalid record state folder deleted: {str(dir_path)}")


class Label(BaseModel):
    """
    display_name looks like:
        key::value
    """

    display_name: str
    description: str = None
    labels: List[dict] = []


class RawDeviceCache(BaseState):
    display_name: str = None
    serial_number: str = None
    description: str = None
    labels: List[dict] = []

    @property
    def state_path(self):
        return RAW_DEVICE_STATE_PATH
