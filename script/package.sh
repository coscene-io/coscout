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
cd "$(dirname "${BASH_SOURCE[0]}")/.."

# check temp dir
TEMP_DIR=$(mktemp -d)
if [ ! -e "$TEMP_DIR" ]; then
  echo >&2 "Failed to create temp directory"
  exit 1
fi

MESH_VERSION="v0.2.8"
COS_VERSION="latest"
TRZSZ_VERSION="1.1.6"

SUPPORT_COS_ARCH=("x86_64" "arm64")
SUPPORT_MESH_ARCH=("amd64" "aarch64")

MESH_BASE_URL=https://coscene-artifacts-production.oss-cn-hangzhou.aliyuncs.com
COS_BASE_URL=https://coscene-download.oss-cn-hangzhou.aliyuncs.com/coscout

# for range support mesh arch
for arch in "${SUPPORT_MESH_ARCH[@]}"; do
  mesh_folder="${TEMP_DIR}/virmesh"
  mkdir -p "${mesh_folder}"

  trzsz_folder="${TEMP_DIR}/trzsz_tar"
  mkdir -p "${trzsz_folder}"

  mesh_download_url=${MESH_BASE_URL}/virmesh/${MESH_VERSION}/virmesh-${arch}
  trzsz_download_url=${MESH_BASE_URL}/trzsz/v${TRZSZ_VERSION}/trzsz_${TRZSZ_VERSION}_linux_${arch}.tar.gz

  curl -L -o "${mesh_folder}/virmesh-${arch}" "${mesh_download_url}"
  curl -L -o "${trzsz_folder}/trzsz_${TRZSZ_VERSION}_linux_${arch}.tar.gz" "${trzsz_download_url}"
done

# for range support cos arch
for arch in "${SUPPORT_COS_ARCH[@]}"; do
  cos_folder="${TEMP_DIR}/cos/${arch}"
  mkdir -p "${cos_folder}"

  cos_download_url=${COS_BASE_URL}/linux/${arch}/${COS_VERSION}/cos
  cos_sha256_url=${COS_BASE_URL}/linux/${arch}/${COS_VERSION}/cos.sha256
  cos_version_url=${COS_BASE_URL}/linux/${arch}/${COS_VERSION}/version

  curl -L -o "${cos_folder}/cos" "${cos_download_url}"
  curl -L -o "${cos_folder}/cos.sha256" "${cos_sha256_url}"
  curl -L -o "${cos_folder}/version" "${cos_version_url}"
done

# tar temp dir
tar -cvzf "${HOME}/cos_binaries.tar.gz" -C "${TEMP_DIR}/" "."

# ls ${HOME}
cd "${HOME}"
echo "${PWD}"
ls -al "${HOME}"
