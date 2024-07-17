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

# define the name of the virtual environment directory
VENV := .venv

$(VENV)/bin/activate:
	pip install virtualenv
	virtualenv -p `which python3` .venv

# default target, when make executed without arguments
all: venv

# venv is a shortcut target
venv: $(VENV)/bin/activate

requirements.txt:
requirements-dev.txt:

.PHONY: install ## sets up environment and installs requirements
install: requirements.txt requirements-dev.txt venv
	$(VENV)/bin/pip install -U pip setuptools wheel
	$(VENV)/bin/pip install -e .[dev] --extra-index-url https://buf.build/gen/python

.PHONY: lint ## Runs flake8 on src, exit if critical rules are broken
lint: venv
	# stop the build if there are Python syntax errors or undefined names
	$(VENV)/bin/flake8 cos --count --select=E9,F63,F7,F82 --show-source --statistics
	# exit-zero treats all errors as warnings. The GitHub editor is 127 chars wide
	$(VENV)/bin/flake8 cos --count --exit-zero --statistics

.PHONY: test ## Run pytest
test: venv
	$(VENV)/bin/pytest . -p no:logging -p no:warnings