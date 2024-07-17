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

dist/cos:
	python3 -m pip install -q -r requirements.txt nuitka
	python3 -m nuitka --standalone --onefile --static-libpython=no --follow-imports --include-package=rosbags --output-filename=cos --output-dir=dist --company-name=coscene --onefile-tempdir-spec="%CACHE_DIR%/%COMPANY%/onefile_%PID%_%TIME%" main.py

ifneq ($(strip $(DOMESTIC)),)
export PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
endif

.PHONY: onefile
onefile: dist/cos
