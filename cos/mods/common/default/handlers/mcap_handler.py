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
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

from mcap.decoder import DecoderFactory
from mcap.reader import make_reader
from mcap.well_known import MessageEncoding
from mcap_protobuf.decoder import DecoderFactory as ProtobufDecoderFactory
from mcap_ros1.decoder import DecoderFactory as Ros1DecoderFactory
from mcap_ros2.decoder import DecoderFactory as Ros2DecoderFactory
from pydantic import BaseModel

from cos.mods.common.default.handlers.handler_interface import HandlerInterface
from cos.mods.common.default.rule_executor import RuleDataItem

_log = logging.getLogger(__name__)


class McapHandler(BaseModel, HandlerInterface):
    def __str__(self):
        return "MCAP Handler"

    @staticmethod
    def supports_static() -> bool:
        return True

    def check_file_path(self, file_path: Path) -> bool:
        return file_path.is_file() and file_path.name.endswith(".mcap")

    def update_path_state(self, file_path: Path, update_func: Callable[[Path, dict], None]):
        with file_path.open("rb") as f:
            reader = make_reader(f)
            if reader.get_summary() is None:
                _log.warning(f"Failed to get summary for mcap file: {file_path}, need reindexing.")
                return

            start_time = reader.get_summary().statistics.message_start_time // 1_000_000_000
            end_time = reader.get_summary().statistics.message_end_time // 1_000_000_000
            update_func(
                file_path,
                {
                    "size": file_path.stat().st_size,
                    "start_time": start_time,
                    "end_time": end_time,
                },
            )

    def msg_iterator(self, file_path: Path):
        with file_path.open("rb") as f:
            reader = make_reader(
                f,
                decoder_factories=[JsonDecoderFactory(), Ros1DecoderFactory(), Ros2DecoderFactory(), ProtobufDecoderFactory()],
            )
            for schema, channel, message, decoded_msg in reader.iter_decoded_messages(log_time_order=True):
                yield RuleDataItem(
                    topic=channel.topic, msg=decoded_msg, ts=message.log_time // 1_000_000_000, msgtype=schema.name
                )


class JsonDecoderFactory(DecoderFactory):
    def decoder_for(self, message_encoding, schema):
        if message_encoding != MessageEncoding.JSON:
            return None

        def decoder(data: bytes):
            return json.loads(data, object_hook=lambda d: SimpleNamespace(**d))

        return decoder
