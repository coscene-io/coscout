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

import json
import logging
import os
import platform
import random
import shutil
import threading
import time
import uuid
from datetime import datetime, timedelta
from functools import partial
from pathlib import Path

from pydantic import BaseModel
from strictyaml import load

from cos.collector import Mod
from cos.constant import COS_DEFAULT_CONFIG_PATH, DEFAULT_MOD_STATE_DIR, DEFAULT_MOD_TEMP_DIR
from cos.core.api import ApiClient
from cos.core.exceptions import DeviceNotFound
from cos.core.models import FileInfo, RecordCache
from cos.mods.common.default.file_state_handler import FileStateHandler
from cos.mods.common.default.handlers import LogHandler
from cos.mods.common.task.task_handler import TaskHandler
from cos.utils import flatten

_log = logging.getLogger(__name__)


class DefaultModConfig(BaseModel):
    enabled: bool = False
    base_dirs: list[str] = None
    sn_file: str | None = ""
    sn_field: str | None = ""
    ros2_customized_msgs_dirs: list[str] = []
    upload_files: list[str] = []


class DefaultMod(Mod):
    def __init__(self, api_client: ApiClient, conf: dict = None):
        if not conf:
            _conf = DefaultModConfig()
        else:
            _conf = DefaultModConfig.model_validate(conf)

        self._api_client = api_client
        self.conf = _conf
        self.log_thread_name = "cos-log-listener"
        self.task_thread_name = "cos-task-handler"

        super().__init__()

    @staticmethod
    def __find_error_json(target_dir: Path):
        for file_path in target_dir.glob("**/*.json"):
            yield str(file_path)

    @staticmethod
    def __update_error_json(error_json, error_json_path):
        with open(error_json_path, "w", encoding="utf8") as fp:
            json.dump(error_json, fp, indent=4)

    def handle_error_json(self, error_json_path: str):
        with open(error_json_path, "r", encoding="utf8") as fp:
            error_json = json.load(fp)

        # 如果 flag（文件已经找齐）为 True 并且还未 uploaded.
        if "flag" in error_json and error_json["flag"] and "uploaded" not in error_json and "skipped" not in error_json:
            source_file = Path(error_json_path)
            start_time = error_json.get("startTime")
            rc = RecordCache(
                timestamp=int(start_time),
            ).load_state()
            if error_json.get("projectName"):
                rc.project_name = error_json.get("projectName")

            target_file = Path(rc.base_dir_path) / source_file.name
            if not target_file.exists():
                target_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(source_file, target_file)
                _log.info(f"==> Copy error json file to record folder: {target_file}")

            files = {str(target_file): FileInfo(filepath=str(target_file), filename=target_file.name)}
            for key in ["bag", "log", "files"]:
                for filepath in error_json.get(key, []):
                    filename = key + "/" + Path(filepath).name
                    files[filename] = FileInfo(filepath=filepath, filename=filename)
            for key in ["zips"]:
                for filepath in error_json.get(key, []):
                    filename = Path(filepath).name
                    files[filename] = FileInfo(filepath=filepath, filename=filename)
            for dir_base_path in error_json.get("dirs", []):
                for filepath in Path(dir_base_path).glob("**/*"):
                    if filepath.is_file():
                        filename = str(filepath.relative_to(Path(dir_base_path).parent))
                        files[filename] = FileInfo(filepath=filepath, filename=filename)

            rc.file_infos = list(files.values())
            rc.record = {
                "title": error_json.get("record", {}).get("title", "Device Auto Upload - " + str(rc.timestamp)),
                "description": error_json.get("record", {}).get("description", "Device Auto Upload"),
            }
            rc.labels = error_json.get("record", {}).get("labels", [])
            rc.paths_to_delete = error_json.get("paths_to_delete", [])
            rc.save_state()
            _log.info(f"==> Converted error log to record state: {rc.state_path}")

            # 把上传状态写回json
            error_json["uploaded"] = True
            self.__update_error_json(error_json, error_json_path)
            _log.info(f"==> Handle err file done: {error_json_path}")
        else:
            _log.debug(f"==> Skip handle err file: {error_json_path}")

    @staticmethod
    def __find_files_and_update_error_json(error_json_path: str, source_dirs: list[Path], temp_dir: Path):
        with open(error_json_path, "r", encoding="utf8") as fp:
            error_json = json.load(fp)

        if "flag" not in error_json or error_json["flag"] or "cut" not in error_json:
            return

        if datetime.now().timestamp() < error_json["cut"]["end"]:
            return

        start_time = error_json["cut"]["start"]
        end_time = error_json["cut"]["end"]
        file_state_handler = FileStateHandler.get_instance()
        file_state_handler.update_dirs(source_dirs)
        error_json_id, _ = os.path.splitext(os.path.basename(error_json_path))
        temp_files_dir = temp_dir / error_json_id
        temp_files_dir.mkdir(parents=True, exist_ok=True)

        _log.info(
            f"==> Search for files in {','.join([s.name for s in source_dirs])}"
            + f", start_time: {start_time}, end_time: {end_time}"
        )
        raw_files = file_state_handler.get_files(source_dirs, start_time, end_time)
        _log.info(f"==> Found files: {raw_files}")
        raw_files += error_json["cut"]["extraFiles"]

        _log.info(
            f"==> Search for dirs in {','.join([s.name for s in source_dirs])}"
            + f", start_time: {start_time}, end_time: {end_time}"
        )
        raw_dirs = file_state_handler.get_files(source_dirs, start_time, end_time, True)
        _log.info(f"==> Found dirs: {raw_dirs}")

        bag_files = []
        log_files = []
        other_files = []
        dirs = []
        zips = []
        for dir_name in raw_dirs:
            dir_path = Path(dir_name)
            cur_dir = temp_files_dir / dir_path.name
            shutil.copytree(dir_path, cur_dir)
            dirs.append(str(cur_dir))
        for file in raw_files:
            # todo: use handlers to handle different file types
            try:
                if Path(file).is_file():
                    if file.endswith(".bag"):
                        dst_path = shutil.copy(file, temp_files_dir)
                        bag_files.append(dst_path)
                    elif file.endswith(".log"):
                        dst_path = LogHandler.prepare_cut(Path(file), temp_files_dir, start_time, end_time)
                        log_files.append(dst_path)
                    else:
                        dst_path = shutil.copy(file, temp_files_dir)
                        other_files.append(dst_path)
                elif Path(file).is_dir():
                    dst_path = (temp_files_dir / Path(file).name).with_suffix(".zip")
                    shutil.make_archive(
                        str(dst_path.with_suffix("")),
                        "zip",
                        Path(file).parent,
                        Path(file).name,
                    )
                    zips.append(str(dst_path))
            except Exception:
                _log.error(f"==> Cut file failed: {file}", exc_info=True)

        error_json["bag"] = bag_files
        error_json["log"] = log_files
        error_json["files"] = other_files
        error_json["dirs"] = dirs
        error_json["zips"] = zips
        error_json["flag"] = True
        error_json["startTime"] = int(time.time() * 1000) + random.randint(1, 1000)
        error_json["paths_to_delete"] = [str(temp_files_dir)]

        with open(error_json_path, "w", encoding="utf8") as fp:
            json.dump(error_json, fp, indent=4)

    @staticmethod
    def __dump_upload_json(
        before,
        title,
        description,
        labels,
        extra_files,
        state_dir: Path,
        project_name,
        trigger_ts,
        after=0,
    ):
        assert before >= 0 or after >= 0, "before or after must be greater than 0"
        start_time_raw = datetime.fromtimestamp(trigger_ts) - timedelta(minutes=before)
        end_time_raw = datetime.fromtimestamp(trigger_ts) + timedelta(minutes=after)
        start_time = int(start_time_raw.timestamp())
        end_time = int(end_time_raw.timestamp())

        json_path = state_dir / f"{uuid.uuid4()}.json"
        json_path.parent.mkdir(parents=True, exist_ok=True)

        upload_data = {
            "flag": False,
            "projectName": project_name,
            "record": {},
            "cut": {
                "extraFiles": extra_files,
                "start": start_time,
                "end": end_time,
            },
        }
        if title:
            upload_data["record"]["title"] = title
        if description:
            upload_data["record"]["description"] = description
        if labels:
            upload_data["record"]["labels"] = labels

        DefaultMod.__update_error_json(upload_data, json_path)

    def __handle_upload_files(self, source_dirs: list[Path], state_dir: Path):
        file_state_handler = FileStateHandler.get_instance()
        _log.info(f"Updating file states in dir: {source_dirs}")
        file_state_handler.update_dirs(source_dirs)

        _log.info(f"==> Search for unprocessed files in {source_dirs}")
        for source_dir in source_dirs:
            for file in source_dir.iterdir():
                file_state_handler.static_file_diagnosis(
                    self._api_client,
                    file,
                    partial(DefaultMod.__dump_upload_json, state_dir=state_dir),
                )

    def run(self):
        if not self.conf.enabled:
            _log.info("Default Mod is not enabled, skip!")
            return

        self.start_task_handler(self._api_client, self.conf.upload_files)
        if not self.conf.base_dirs or len(self.conf.base_dirs) == 0:
            _log.info("Default Mod base dirs is empty, skip!")
            return

        # todo Find a better place to initialize FileStateHandler
        FileStateHandler.get_instance(self.conf.ros2_customized_msgs_dirs)
        base_dirs: list[Path] = []
        for base_dir_str in self.conf.base_dirs:
            base_dir = Path(base_dir_str).absolute()
            base_dir.mkdir(parents=True, exist_ok=True)
            base_dirs.append(base_dir)

        state_dir = DEFAULT_MOD_STATE_DIR
        state_dir.mkdir(parents=True, exist_ok=True)
        temp_dir = DEFAULT_MOD_TEMP_DIR
        temp_dir.mkdir(parents=True, exist_ok=True)
        self.start_log_listener(base_dirs, state_dir)

        # handle waiting to upload files
        self.__handle_upload_files(base_dirs, state_dir)
        # handle error json files
        _log.info(f"==> Search for new error json {str(state_dir)}")
        for error_json_path in self.__find_error_json(state_dir):
            # noinspection PyBroadException
            try:
                self.__find_files_and_update_error_json(error_json_path, base_dirs, temp_dir)
                self.handle_error_json(error_json_path)
            except Exception:
                # 打印错误，但保证循环不被打断
                _log.error(f"An error occurred when handling: {error_json_path}", exc_info=True)

    def start_log_listener(self, source_dirs: list[Path], state_dir: Path):
        log_thread_flag = False

        for t in threading.enumerate():
            if t.name == self.log_thread_name:
                log_thread_flag = True

        if not log_thread_flag:
            t = threading.Thread(
                target=LogHandler().diagnose,
                args=(
                    self._api_client,
                    source_dirs,
                    partial(
                        DefaultMod.__dump_upload_json,
                        state_dir=state_dir,
                    ),
                ),
                name=self.log_thread_name,
                daemon=True,
            )
            t.start()
            _log.info("Thread start log listener")
        else:
            _log.info("Thread already start log listener, skip!")

    def start_task_handler(self, api_client: ApiClient, upload_files: list[str]):
        if upload_files is None:
            upload_files = []

        task_thread_flag = False
        for t in threading.enumerate():
            if t.name == self.task_thread_name:
                task_thread_flag = True

        if not task_thread_flag:
            t = threading.Thread(
                target=TaskHandler(api_client, upload_files).run,
                args=(),
                name=self.task_thread_name,
                daemon=True,
            )
            t.start()
            _log.info("Thread start handle task")
        else:
            _log.info("Thread task already handle, skip!")

    @staticmethod
    def __generate_device_sn():
        sn_file_path = COS_DEFAULT_CONFIG_PATH.parent / "sn.txt"
        sn_file_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if not sn_file_path.is_file():
                sn = uuid.uuid4().hex
                with open(sn_file_path.absolute(), "w", encoding="utf8") as y:
                    y.write(sn)
        except PermissionError as e:
            raise DeviceNotFound(f"access to {sn_file_path} denied") from e

        with open(sn_file_path.absolute(), "r", encoding="utf8") as y:
            sn = y.read().strip()

        node = platform.node()
        return {
            "serial_number": sn,
            "display_name": f"{node}@{sn}",
            "description": f"node: {node}, sn: {sn}",
        }

    def get_device(self) -> dict[str, str]:
        if not self.conf.sn_file:
            return self.__generate_device_sn()

        sn_file_path = Path(self.conf.sn_file)
        if not sn_file_path.exists():
            return self.__generate_device_sn()

        file_path_str = str(sn_file_path.absolute())
        if file_path_str.endswith(".txt"):
            with open(sn_file_path, "r", encoding="utf8") as y:
                sn = y.read().strip()
            return {
                "serial_number": sn,
                "display_name": sn,
                "description": sn,
            }
        elif self.conf.sn_field and (
            file_path_str.endswith(".json") or file_path_str.endswith(".yaml") or file_path_str.endswith(".yml")
        ):
            with open(sn_file_path, "r", encoding="utf8") as y:
                try:
                    _data = load(y.read()).data
                    flatten_data = flatten(_data)
                except Exception:
                    _log.error("Failed to load sn file", exc_info=True)
                    return self.__generate_device_sn()
            sn = flatten_data.get(self.conf.sn_field)
            if not sn:
                _log.error("Failed to get sn field", exc_info=True)
                raise DeviceNotFound(f"Failed to get sn field from {sn_file_path}")
            return {
                "serial_number": sn,
                "display_name": sn,
                "description": sn,
            }
        return self.__generate_device_sn()

    def convert_code(self, code_json):
        code_list = []
        if isinstance(code_json, list):
            code_list = code_json
        elif isinstance(code_json, dict):
            code_list = code_json.get("msg", [])

        return {str(item.get("code", "")): str(item.get("messageCN", "未知错误")) for item in code_list}

    def find_files(self, trigger_time):
        pass
