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

## check root user
#if [[ "$EUID" -ne 0 ]]; then
#  echo "Please run as root user" >&2
#  exit 1
#fi

# check temp dir
TEMP_DIR=$(mktemp -d)
if [ ! -e "$TEMP_DIR" ]; then
  echo >&2 "Failed to create temp directory"
  exit 1
fi
cleanup() {
  echo "Cleaning up temp directory $TEMP_DIR"
  [[ -n "$TEMP_DIR" && -d "$TEMP_DIR" ]] && rm -rf "$TEMP_DIR"
}
trap cleanup EXIT SIGINT SIGTERM

# Set download ARCH based on system architecture
ARCH=$(uname -m)
MESH_ARCH=""
case "$ARCH" in
x86_64)
  MESH_ARCH="amd64"
  ;;
arm64 | aarch64)
  ARCH="arm64"
  MESH_ARCH="aarch64"
  ;;
*)
  echo "Unsupported architecture: $ARCH. Only x86_64 and arm64 are supported." >&2
  exit 1
  ;;
esac

# Check if tar installed
if ! command -v tar &>/dev/null; then
  echo "tar is required but not installed. Please install it using: 'sudo apt-get install -y tar'" >&2
  exit 1
fi

# default value
DEFAULT_IMPORT_CONFIG=cos://organizations/current/configMaps/device.collector
DEFAULT_CODE_URL=cos://organizations/current/configMaps/device.errorCode

# user input value
SERVER_URL=""
PROJECT_SLUG=""
ORG_SLUG=""
USE_LOCAL=""
BETA=0
DISABLE_SYSTEMD=0
REMOVE_CONFIG=0
MOD="default"
SN_FILE=""
SN_FIELD=""

VIRMESH_ENDPOINT=""
ARTIFACT_BASE_URL=https://coscene-artifacts-production.oss-cn-hangzhou.aliyuncs.com
VIRMESH_DOWNLOAD_URL=${ARTIFACT_BASE_URL}/virmesh/v0.2.8/virmesh-${MESH_ARCH}
TRZSZ_DOWNLOAD_URL=${ARTIFACT_BASE_URL}/trzsz/v1.1.6/trzsz_1.1.6_linux_${MESH_ARCH}.tar.gz

help() {
  cat <<EOF
usage: $0 [OPTIONS]

    --help               Show this message
    --server_url         Api server url, e.g. https://api.coscene.cn
    --project_slug       The slug of the project to upload to
    --org_slug           The slug of the organization device belongs to, project_slug or org_slug should be provided
    --beta               Use beta version for cos
    --use_local          Use local binary file zip path e.g. /xx/path/xx.zip
    --disable_systemd    Disable systemd service installation
    --mod                Select the mod to install - gs, agi, task, default (default is 'default')
    --virmesh_endpoint   Virmesh endpoint, e.g. https://api.mesh.staging.coscene.cn/mesh, will skip if not provided
    --sn_file            The file path of the serial number file, will skip if not provided
    --sn_field           The field name of the serial number, should be provided with sn_file, unique field to identify the device
    --remove_config      Remove all config files, current device will be treated as a new device.
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

error_exit() {
  echo "ERROR: $1" >&2
  exit 1
}

handle_error() {
  echo "An error occurred. Exiting."
  exit 1
}
trap handle_error ERR

download_file() {
  local dest=$1
  local url=$2
  local verify_cert=${3:-1} # Default to verifying the cert if not provided

  if [[ "$verify_cert" -eq 0 ]]; then
    curl -SLko "$dest" "$url" || error_exit "Failed to download $url without verifying the certificate"
  else
    curl -SLo "$dest" "$url" || error_exit "Failed to download $url"
  fi
}

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
  --org_slug=*)
    ORG_SLUG="${1#*=}"
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
    if [[ "$mod_value" == "gs" ]] || [[ "$mod_value" == "agi" ]] || [[ "$mod_value" == "task" ]] || [[ "$mod_value" == "default" ]]; then
      MOD="$mod_value"
    else
      echo "Invalid value for --mod. Allowed values are 'gs', 'agi', 'task', 'default'."
      exit 1
    fi
    ;;
  --virmesh_endpoint=*)
    VIRMESH_ENDPOINT="${1#*=}"
    shift
    ;;
  --sn_file=*)
    SN_FILE="${1#*=}"
    shift
    ;;
  --sn_field=*)
    SN_FIELD="${1#*=}"
    shift
    ;;
  --remove_config)
    REMOVE_CONFIG=1
    shift
    ;;
  *)
    echo "unknown option: $1"
    help
    exit 1
    ;;
  esac
done

# enable linger
CUR_USER=$(whoami)
echo "Enabling linger for user: $CUR_USER"
sudo loginctl enable-linger "$CUR_USER"

if [ -z "$HOME" ]; then
    echo "'HOME' environment variable is not set"
    exit 1
fi

# get user input
get_user_input SERVER_URL "please input server_url: " "${SERVER_URL}"
echo "server_url is ${SERVER_URL}"
echo "org_slug is ${ORG_SLUG}"
echo "project_slug is ${PROJECT_SLUG}"
echo "virmesh_endpoint is ${VIRMESH_ENDPOINT}"
echo "sn_file is ${SN_FILE}"
echo "sn_field is ${SN_FIELD}"

# check org_slug and project_slug
# Check if both ORG_SLUG and PROJECT_SLUG are empty
if [[ -z $ORG_SLUG && -z $PROJECT_SLUG ]]; then
  echo "ERROR: Both org_slug and project_slug cannot be empty. One of them must be specified. Exiting."
  exit 1
fi

# Check if both ORG_SLUG and PROJECT_SLUG are not empty
if [[ -n $ORG_SLUG && -n $PROJECT_SLUG ]]; then
  echo "ERROR: Both org_slug and project_slug cannot be specified at the same time. Only one of them must be specified. Exiting."
  exit 1
fi

# check sn_file and sn_field
# Check if SN_FILE is specified
if [[ -n $SN_FILE ]]; then
  # Check if SN_FILE has valid extension
  valid_extensions=(.txt .json .yaml .yml)
  extension="${SN_FILE##*.}"
  if [[ ! " ${valid_extensions[*]} " =~ $extension ]]; then
    echo "ERROR: sn file has an invalid extension. Only .txt, .json, .yaml, .yml extensions are allowed. Exiting."
    exit 1
  fi

  # Check if SN_FILE exists
  if [[ ! -f $SN_FILE ]]; then
    echo "ERROR: sn file does not exist. Exiting."
    exit 1
  fi

  # Check if extension is not .txt and SN_FIELD is empty
  echo "extension is $extension"
  if [[ $extension != "txt" && -z $SN_FIELD ]]; then
    echo "ERROR: --sn_field is not specified when sn file exist. Exiting."
    exit 1
  fi
fi

# check systemd
if [[ $DISABLE_SYSTEMD -eq 0 ]] && [ "$(ps --no-headers -o comm 1)" != "systemd" ]; then
  echo "Current system is not using systemd."
  exit 1
fi

# check local file path
# Check if user specified local binary file
if [[ -n $USE_LOCAL ]]; then
  # Check if the file exists
  if [[ ! -f $USE_LOCAL ]]; then
    echo "ERROR: Specified file does not exist: $USE_LOCAL" >&2
    exit 1
  fi

  # Check if it is a tar.gz file
  if [[ ${USE_LOCAL: -7} != ".tar.gz" ]]; then
    echo "ERROR: The file specified is not a tar.gz archive. Exiting."
    exit 1
  fi

  # Extract files
  echo "Extracting $USE_LOCAL..."
  mkdir -p "$TEMP_DIR/cos_binaries"
  tar -xzf "$USE_LOCAL" -C "$TEMP_DIR/cos_binaries" || error_exit "Failed to extract $USE_LOCAL"
fi

echo "Start install virmesh..."
format() {
  local input=$1
  echo "${input//[\"|.]/}"
}

# check old virmesh binary
if [ -e /usr/local/bin/virmesh ]; then
  echo "Previously installed version:"
  /usr/local/bin/virmesh -V
fi

if [[ -z $VIRMESH_ENDPOINT ]]; then
  echo "Virmesh endpoint is empty, skip virmesh installation."
else
  VERSION_ID=$(format "$(awk -F= '$1=="VERSION_ID" { print $2 ;}' /etc/os-release)")
  SYSTEM_NAME=$(format "$(awk -F= '$1=="NAME" { print $2 ;}' /etc/os-release)")
  VERIFY_CERT=1
  echo "Downloading new virmesh binary..."
  if [[ -z $USE_LOCAL && $SYSTEM_NAME = "Ubuntu" && $VERSION_ID -le 1606 ]]; then
    read -r -p "Your system version is outdated and does not have the latest root certificate. You may need to bypass the certificate verification process. Do you want to proceed? 你的操作系统版本太低，没有最新的根证书，需要忽略证书验证吗？ [Y/N]" anwser
    case $anwser in
    Y | y)
      VERIFY_CERT=0
      ;;
    *) ;;
    esac
  fi

  if [[ -n $USE_LOCAL ]]; then
    mv -f "$TEMP_DIR/cos_binaries/virmesh/virmesh-${MESH_ARCH}" "$TEMP_DIR"/virmesh
  else
    download_file "$TEMP_DIR"/virmesh $VIRMESH_DOWNLOAD_URL $VERIFY_CERT
  fi

  chmod +x "$TEMP_DIR"/virmesh
  echo "Installed new virmesh version:"
  "$TEMP_DIR"/virmesh -V

  sudo mv -f "$TEMP_DIR"/virmesh /usr/local/bin/virmesh

  echo "Downloading new trzsz binary..."
  if [[ -n $USE_LOCAL ]]; then
    cp "$TEMP_DIR/cos_binaries/trzsz_tar/trzsz_1.1.6_linux_${MESH_ARCH}.tar.gz" "$TEMP_DIR"/trzsz.tar.gz
  else
    download_file "$TEMP_DIR"/trzsz.tar.gz $TRZSZ_DOWNLOAD_URL $VERIFY_CERT
  fi

  echo "unzip trzsz..."
  mkdir -p "$TEMP_DIR"/trzsz
  tar -xzf "$TEMP_DIR"/trzsz.tar.gz -C "$TEMP_DIR"/trzsz --strip-components 1
  chmod -R +x "$TEMP_DIR"/trzsz
  sudo mv -f "$TEMP_DIR"/trzsz/* /usr/local/bin/
  rm -rf "$TEMP_DIR"/trzsz.tar.gz

  if [[ $DISABLE_SYSTEMD -eq 0 ]]; then
    echo "Installing systemd service..."
    sudo tee /etc/systemd/system/virmesh.service >/dev/null <<EOF

[Unit]
Description=Virmesh Client Daemon

[Service]
WorkingDirectory=/etc
ExecStart=/usr/local/bin/virmesh --endpoint $VIRMESH_ENDPOINT --allow-ssh

[Install]
WantedBy=multi-user.target
EOF
    sudo systemctl daemon-reload

    echo "Starting virmesh service..."
    sudo systemctl is-active --quiet virmesh && sudo systemctl stop virmesh
    sudo systemctl enable virmesh
    sudo systemctl start virmesh
  else
    echo "Skipping systemd service installation, just install virmesh binary..."
  fi
  echo "Successfully installed virmesh."
fi

echo "Start install cos..."

# remove old config before install
if [[ $REMOVE_CONFIG -eq 1 ]]; then
  echo "remove exists config file."
  rm -rf "$HOME"/.local/state/cos
  rm -rf "$HOME"/.config/cos
  rm -rf "$HOME"/.cache/coscene
  rm -rf "$HOME"/.cache/cos
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
COS_SHELL_BASE="$HOME/.local"

# make some directories
COS_CONFIG_DIR="$HOME/.config/cos"
COS_STATE_DIR="$HOME/.local/state/cos"
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
  org_slug: $ORG_SLUG
  type: grpc

updater:
  enabled: true
  artifact_base_url: $DEFAULT_BASE_URL
  binary_path: $COS_SHELL_BASE/bin/cos

event_code:
  enabled: true
  code_json_url: $DEFAULT_CODE_URL

mod:
  name: $MOD
  conf:
    enabled: true
    sn_file: $SN_FILE
    sn_field: $SN_FIELD

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
  TMP_FILE="$TEMP_DIR/cos_binaries/cos/$ARCH/cos"
  if [[ ! -f $TMP_FILE ]]; then
    echo "ERROR: Failed to download cos binary. Exiting."
    exit 1
  fi
  REMOTE_SHA256=$(cat "$TEMP_DIR/cos_binaries/cos/$ARCH/cos.sha256")
else
  mkdir -p "$TEMP_DIR/cos_binaries/cos/$ARCH"
  TMP_FILE="$TEMP_DIR/cos_binaries/cos/$ARCH/cos"
  download_file "$TMP_FILE" "$DEFAULT_BINARY_URL"
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
#  echo "Installing the systemd service requires root permissions."
#  cat >/lib/systemd/system/cos.service <<EOL

  USER_SYSTEMD_DIR="$HOME/.config/systemd/user"
  mkdir -p "$USER_SYSTEMD_DIR"
  cat >"$USER_SYSTEMD_DIR"/cos.service <<EOL
[Unit]
Description=coScout: Data Collector by coScene
Documentation=https://github.com/coscene-io/sample-json-api-files
Wants=network-online.target
After=network.target network-online.target
StartLimitBurst=10
StartLimitIntervalSec=86400

[Service]
Type=simple
WorkingDirectory=$HOME/.local/state/cos
StandardOutput=syslog
StandardError=syslog
CPUQuota=10%
ExecStartPre=/bin/sh -c "rm -rf $HOME/.cache/coscene/onefile_*"
ExecStart=$COS_SHELL_BASE/bin/cos daemon
SyslogIdentifier=cos
RestartSec=60
Restart=always

[Install]
WantedBy=multi-user.target
EOL
  echo "Created cos.service systemd file: $USER_SYSTEMD_DIR/cos.service"

  echo "Starting cos service for $CUR_USER..."
  systemctl --user daemon-reload
  systemctl --user is-active --quiet cos && systemctl --user stop cos
  systemctl --user enable cos
  systemctl --user start cos
  echo "Done."
else
  echo "Skipping systemd service installation, just install cos binary..."
fi

echo "Successfully installed cos."

echo "Installation completed successfully 🎉, you can use 'journalctl --user-unit=cos -f -n 50' to check the logs."
exit 0
