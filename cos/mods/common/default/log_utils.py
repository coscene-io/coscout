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
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import chardet

_log = logging.getLogger(__name__)

hint_options = [
    (re.compile(r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}"), "%Y-%m-%d %H:%M:%S"),
    (re.compile(r"\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2}"), "%Y/%m/%d %H:%M:%S"),
    (re.compile(r"\d{10}"), "%Y%m%d%H"),
]
ts_schema = [
    (
        re.compile(r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}.\d{3}"),
        "%Y-%m-%d %H:%M:%S.%f",
    ),
    (
        re.compile(r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2},\d{3}"),
        "%Y-%m-%d %H:%M:%S,%f",
    ),
    (re.compile(r"\d{4}\s+\d{2}:\d{2}:\d{2}.\d{6}"), "%m%d %H:%M:%S.%f"),
    (re.compile(r"[a-zA-Z]{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}"), "%b %d %H:%M:%S"),
    (re.compile(r"\d{2}:\d{2}:\d{2}.\d{3}"), "%H:%M:%S.%f"),
]


def get_timestamp_hint_from_file(file_path: Path, encoding: str):
    """
    Get the timestamp hint from filename or the first line of the file.
    Prioritize the timestamp hint from filename.
    """

    def get_hint_from_text(text: str):
        for regex, date_format in hint_options:
            time_candidate = regex.search(text)
            if time_candidate:
                try:
                    return datetime.strptime(time_candidate.group(), date_format).replace(tzinfo=timezone(timedelta(hours=8)))
                except ValueError:
                    pass
        return None

    filename_hint = get_hint_from_text(file_path.name)
    if filename_hint:
        return filename_hint

    with file_path.open("r", encoding=encoding) as f:
        first_line = f.readline()

    return get_hint_from_text(first_line)


def get_timestamp_with_hint(dt: datetime, hint: datetime, date_format: str):
    if hint:
        # We have the assumption that either the entire date info is missing
        # or only the year is missing
        if "%d" not in date_format:
            candidate = dt.replace(year=hint.year, month=hint.month, day=hint.day)
            if candidate < hint:
                return candidate + timedelta(days=1)
            return candidate
        elif "%Y" not in date_format:
            candidate = dt.replace(year=hint.year)
            if candidate < hint:
                return candidate.replace(year=hint.year + 1)
            return candidate
    else:
        if "%d" not in date_format:
            candidate = dt.replace(
                year=datetime.now().year,
                month=datetime.now().month,
                day=datetime.now().day,
            )
            if candidate > datetime.now().replace(tzinfo=timezone(timedelta(hours=8))):
                return candidate - timedelta(days=1)
            return candidate
        elif "%Y" not in date_format:
            candidate = dt.replace(year=datetime.now().year)
            if candidate > datetime.now().replace(tzinfo=timezone(timedelta(hours=8))):
                return candidate.replace(year=datetime.now().year - 1)
            return candidate
    # Return the original timestamp if full date time info is present
    return dt


def get_timestamp_from_line(line: str, hint: datetime):
    for regex, date_format in ts_schema:
        time_candidate = regex.search(line)
        if time_candidate:
            try:
                parsed_time = datetime.strptime(time_candidate.group(), date_format).replace(
                    tzinfo=timezone(timedelta(hours=8))
                )
                return get_timestamp_with_hint(parsed_time, hint, date_format)
            except ValueError:
                pass

    return None


CHUNK_SIZE = 16 * 1024
BUFFER_SIZE = 512
ATTEMPT_LIMIT = 5


def get_end_timestamp(file_path: Path):
    file_size = file_path.stat().st_size
    file_encoding = get_file_encoding(file_path)
    hint = get_timestamp_hint_from_file(file_path, file_encoding)
    with file_path.open("r", encoding=file_encoding, errors="ignore") as f:
        for attempt in range(ATTEMPT_LIMIT):
            end_offset = file_size - attempt * CHUNK_SIZE
            start_offset = end_offset - CHUNK_SIZE - BUFFER_SIZE
            start_offset = max(0, start_offset)
            if end_offset <= 0:
                _log.warning(f"Failed to get end timestamp from {file_path}")
                return None
            f.seek(start_offset)
            chunk = f.read(CHUNK_SIZE + BUFFER_SIZE)
            for line in reversed(chunk.splitlines()):
                timestamp_candidate = get_timestamp_from_line(line, hint)
                if timestamp_candidate:
                    return int(timestamp_candidate.timestamp())
    _log.warning(f"Failed to get end timestamp from {file_path}, searched last {ATTEMPT_LIMIT * CHUNK_SIZE} bytes")
    return None


def get_start_timestamp(file_path: Path):
    file_size = file_path.stat().st_size
    file_encoding = get_file_encoding(file_path)
    hint = get_timestamp_hint_from_file(file_path, file_encoding)
    with file_path.open("r", encoding=file_encoding, errors="ignore") as f:
        for attempt in range(ATTEMPT_LIMIT):
            start_offset = attempt * CHUNK_SIZE
            if start_offset >= file_size:
                _log.warning(f"Failed to get start timestamp from {file_path}")
                return None
            f.seek(start_offset)
            chunk = f.read(CHUNK_SIZE + BUFFER_SIZE)
            timestamp_candidate = get_timestamp_from_line(chunk, hint)
            if timestamp_candidate:
                return int(timestamp_candidate.timestamp())
    _log.warning(f"Failed to get start timestamp from {file_path}, searched first {ATTEMPT_LIMIT * CHUNK_SIZE} bytes")
    return None


ACCEPTED_SPECIAL_ENCODINGS = ["GB2312"]


def get_file_encoding(file_path: Path):
    with file_path.open("rb") as f:
        file_encoding = chardet.detect(f.read(CHUNK_SIZE))["encoding"]
        if file_encoding in ACCEPTED_SPECIAL_ENCODINGS:
            return file_encoding
        return "utf8"
