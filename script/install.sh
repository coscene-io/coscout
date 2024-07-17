#!/usr/bin/env bash
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


set -Eeuo pipefail

# default value
DEFAULT_IMPORT_CONFIG=cos://organizations/current/configMaps/device.collector
DEFAULT_CODE_URL=cos://organizations/current/configMaps/device.errorCode

# user input value
SERVER_URL=""
PROJECT_SLUG=""
USE_LOCAL=""
BETA=0
DISABLE_SYSTEMD=0
MOD="default"

help() {
  cat <<EOF
usage: $0 [OPTIONS]

    --help               Show this message
    --server_url         Api server url, e.g. https://api.coscene.cn
    --project_slug       The slug of the project to upload to
    --beta               Use beta version
    --use_local          Use local binary file zip path e.g. /xx/path/xx.zip
    --disable_systemd    Disable systemd service installation
    --mod                Select the mod to install - gs, default (default is 'default')
EOF
}

get_user_input() {
  local varname="$1"
  local prompt="$2"
  local inputValue="$3"

  while [[ -z ${inputValue} ]]; do
    read -r -p "${prompt}" inputValue
    if [[ -n ${inputValue} ]]; then
      eval "${varname}=\${inputValue}"
    fi
  done
}

handle_error() {
  echo "An error occurred. Exiting."
  exit 1
}
trap handle_error ERR

# check root user
if [ "$EUID" -ne 0 ]; then
  echo "Please run as root user"
  exit 1
fi

# Set download ARCH based on system architecture
case $(uname -m) in
x86_64)
  ARCH="x86_64"
  ;;
arm64 | aarch64)
  ARCH="arm64"
  ;;
*)
  echo "Unsupported architecture: $ARCH, only support x86_64 and arm64"
  exit 1
  ;;
esac

# get user input
while test $# -gt 0; do
  case $1 in
  --help)
    help
    exit 0
    ;;
  --server_url=*)
    SERVER_URL="${1#*=}"
    shift # past argument=value
    ;;
  --project_slug=*)
    PROJECT_SLUG="${1#*=}"
    shift # past argument=value
    ;;
  --beta)
    BETA=1
    shift # past argument
    ;;
  --use_local=*)
    USE_LOCAL="${1#*=}"
    shift # past argument=value
    ;;
  --disable_systemd)
    DISABLE_SYSTEMD=1
    shift # past argument
    ;;
  --mod=*)
    mod_value="${1#*=}"
    shift
    if [[ "$mod_value" == "gs" ]] || [[ "$mod_value" == "default" ]]; then
      MOD="$mod_value"
    else
      echo "Invalid value for --mod. Allowed values are 'gs', 'default'."
      exit 1
    fi
    ;;
  *)
    echo "unknown option: $1"
    help
    exit 1
    ;;
  esac
done

# Check if tar installed
if [[ -z $USE_LOCAL ]] && ! command -v tar &>/dev/null; then
  echo >&2 "tar is required but it's not installed. Use 'sudo apt-get install -y tar' to install tar tool."
  exit 1
fi

# check systemd
if [[ $DISABLE_SYSTEMD -eq 0 ]] && [ "$(ps --no-headers -o comm 1)" != "systemd" ]; then
  echo "Current system is not using systemd."
  exit 1
fi

# set some variables
LATEST_BASE_URL="https://download.coscene.cn/coscout/linux/$ARCH/latest"
BETA_BASE_URL="https://download.coscene.cn/coscout/linux/$ARCH/beta"
DEFAULT_BASE_URL="$LATEST_BASE_URL"
DEFAULT_BINARY_URL="$LATEST_BASE_URL/cos"

# set binary_url based on beta flag
if [[ $BETA -eq 1 ]]; then
  DEFAULT_BINARY_URL="$BETA_BASE_URL/cos"
  DEFAULT_BASE_URL="$BETA_BASE_URL"
fi

# region config
# get user input
get_user_input SERVER_URL "please input server_url: " "${SERVER_URL}"
get_user_input PROJECT_SLUG "please input project_slug: " "${PROJECT_SLUG}"
echo "server_url is ${SERVER_URL}"
echo "project_slug is ${PROJECT_SLUG}"

COS_SHELL_BASE="/usr/local"

# make some directories
COS_CONFIG_DIR="/root/.config/cos"
COS_STATE_DIR="/root/.local/state/cos"
mkdir -p "$COS_CONFIG_DIR" "$COS_STATE_DIR" "$COS_SHELL_BASE/bin"
cat >"${COS_STATE_DIR}/install.state.json" <<EOL
{
  "init_install": true
}
EOL

# create config file
echo "Creating config file..."
# create config file ~/.config/cos/config.yaml
cat >"${COS_CONFIG_DIR}/config.yaml" <<EOL
api:
  server_url: $SERVER_URL
  project_slug: $PROJECT_SLUG

updater:
  artifact_base_url: $DEFAULT_BASE_URL
  binary_path: $COS_SHELL_BASE/bin/cos

event_code:
  enabled: true
  code_json_url: $DEFAULT_CODE_URL

mod:
  name: $MOD
  conf:
    enabled: true

__import__:
  - $DEFAULT_IMPORT_CONFIG
  - ${COS_CONFIG_DIR}/local.yaml

__reload__:
  reload_interval_in_secs: 60
EOL

# create local config file
LOCAL_CONFIG_FILE="${COS_CONFIG_DIR}/local.yaml"
if [[ ! -f "$LOCAL_CONFIG_FILE" ]]; then
  echo "{}" >"$LOCAL_CONFIG_FILE"
fi
echo "Created config file: ${COS_CONFIG_DIR}/config.yaml"
# endregion

check_binary() {
  echo -n "  - Checking ${1} executable ... "
  local output
  if ! output=$("$COS_SHELL_BASE"/bin/"${1}" --version 2>&1); then
    echo "Error: $output"
  else
    echo "$output"
    return 0
  fi
  return 1
}

# check old cos binary
if [ -e "$COS_SHELL_BASE/bin/cos" ]; then
  echo "Previously installed version:"
  check_binary cos
fi

# Check if user specified local binary file
if [[ -n $USE_LOCAL ]]; then
  # Check if it is a tar.gz file
  if [[ ${USE_LOCAL: -7} != ".tar.gz" ]]; then
    echo "ERROR: The file specified is not a tar.gz archive. Exiting."
    exit 1
  fi

  # Extract files
  echo "Extracting $USE_LOCAL..."
  mkdir -p /tmp/cos_binaries
  tar -xzf "$USE_LOCAL" -C /tmp/cos_binaries

  TMP_FILE="/tmp/cos_binaries/$ARCH/cos"
  if [[ ! -f $TMP_FILE ]]; then
    echo "ERROR: Failed to download cos binary. Exiting."
    exit 1
  fi

  REMOTE_SHA256=$(cat "/tmp/cos_binaries/$ARCH/cos.sha256")
fi

# Use remote cos binary file
if [[ -z $USE_LOCAL ]]; then
  # download cos binary
  echo "Downloading new cos binary..."
  TMP_FILE=$(mktemp)
  cleanup() {
    if [[ -e "$TMP_FILE" ]]; then
      rm -f "$TMP_FILE"
    fi
  }
  trap cleanup EXIT

  curl -SLo "$TMP_FILE" "$DEFAULT_BINARY_URL"
  # check cos sha256sum
  REMOTE_SHA256=$(curl -sSfL "$DEFAULT_BINARY_URL.sha256")
fi

LOCAL_SHA256=$(sha256sum "$TMP_FILE" | awk '{print $1}')
if [[ "$REMOTE_SHA256" != "$LOCAL_SHA256" ]]; then
  echo "Error: SHA256 mismatch. Exiting."
  exit 1
else
  echo "SHA256 verified. Proceeding."
fi

echo "Installed new cos version:"
mv -f "$TMP_FILE" "$COS_SHELL_BASE/bin/cos"
chmod +x "$COS_SHELL_BASE/bin/cos"
check_binary cos

# check disable systemd, default will install cos.service
if [[ $DISABLE_SYSTEMD -eq 0 ]]; then

  # create cos.service systemd file
  echo "Creating cos.service systemd file..."
  echo "Installing the systemd service requires root permissions."
  cat >/lib/systemd/system/cos.service <<EOL
[Unit]
Description=coScout: Data Collector by coScene
Documentation=https://github.com/coscene-io/sample-json-api-files
Wants=network-online.target
After=network.target network-online.target

[Service]
Type=simple
WorkingDirectory=/root/.local/state/cos
StandardOutput=syslog
StandardError=syslog
CPUQuota=10%
ExecStart=/usr/local/bin/cos daemon
SyslogIdentifier=cos
Restart=always

[Install]
WantedBy=multi-user.target
EOL
  echo "Created cos.service systemd file: /lib/systemd/system/cos.service"

  echo "Starting cos service..."
  systemctl daemon-reload
  systemctl is-active --quiet cos && systemctl stop cos
  systemctl enable cos
  systemctl start cos
  echo "Done."
else
  echo "Skipping systemd service installation, just install cos binary..."
fi
