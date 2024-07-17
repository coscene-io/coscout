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

from cos.mods.common.default.handlers.handler_interface import HandlerInterface
from cos.mods.common.default.handlers.log_handler import LogHandler
from cos.mods.common.default.handlers.mcap_handler import McapHandler
from cos.mods.common.default.handlers.ros1_handler import Ros1Handler
from cos.mods.common.default.handlers.ros2_handler import Ros2Handler

HANDLERS: list[HandlerInterface] = [
    LogHandler(),
    McapHandler(),
    Ros1Handler(),
    Ros2Handler(),
]

__all__ = ["HANDLERS", "HandlerInterface", "LogHandler", "McapHandler", "Ros1Handler", "Ros2Handler"]
