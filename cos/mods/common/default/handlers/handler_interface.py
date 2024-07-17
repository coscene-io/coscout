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

from abc import ABC, abstractmethod
from functools import partial
from pathlib import Path
from typing import Callable

from cos.core.api import ApiClient
from cos.mods.common.default.rule_executor import RuleExecutor


class HandlerInterface(ABC):
    """Handler interface for handling different file types"""

    @staticmethod
    @abstractmethod
    def supports_static() -> bool:
        """Check if the handler is static, by static,
        it means the handler supports handling files that are not changing"""
        pass

    @abstractmethod
    def check_file_path(self, file_path: Path) -> bool:
        """Check if the file path is supported by the handler"""
        pass

    @abstractmethod
    def update_path_state(self, file_path: Path, update_func: Callable[[Path, dict], None]):
        """Update the path state"""
        pass

    def get_file_size(self, file_path: Path) -> int:
        """Get the file path size"""
        return file_path.stat().st_size

    # The following methods are diagnose related
    def diagnose(self, api_client: ApiClient, file_path: Path, upload_fn: partial):
        """Diagnose the file"""
        rule_executor = RuleExecutor(f"{file_path.name} Rule Executor", api_client, self.msg_iterator(file_path), upload_fn)
        rule_executor.execute()

    @abstractmethod
    def msg_iterator(self, file_path: Path):
        """Get an iterator for the messages in the file"""
        pass
