# -*- coding:utf-8 -*-
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
import os
import json
from pathlib import Path

import boto3
import threading
from typing import List
from botocore.exceptions import EndpointConnectionError

from cos.core import request_hook
from cos.utils import tools

_log = logging.getLogger(__name__)


class S3MultipartUploader:
    """
    Represents a class for uploading a file to S3 using multipart.
    Supports resuming.
    """

    # AWS throws EntityTooSmall error for parts smaller than 5 MB
    PART_MINIMUM = int(5e6)

    def __init__(self, s3_client: boto3.client, bucket: str, key: str, file_path: str, part_size_bytes=int(6e6)):
        self.bucket = bucket
        self.key = key
        self.file_path = file_path
        self.file_name = key.split("/files/")[-1]
        _base_filename = os.path.basename(self.file_name)
        self.file_dir = os.path.dirname(os.path.realpath(self.file_path))
        self.multipart_info_file_path = f"{self.file_dir}/.{_base_filename}_multipart.json"
        self.part_size_bytes = part_size_bytes
        self.s3 = s3_client
        self.enabled = True
        self.stop_event = threading.Event()

        assert part_size_bytes >= self.PART_MINIMUM, "part_size is less the minimum part size which is 5MB"

    def _create(self):
        """Creates a internal info file with information about this multipart upload

        Raises:
            Exception: If an info file already exist
        """
        if os.path.isfile(self.multipart_info_file_path):
            raise FileExistsError("file is already in the process of being uploaded")

        mpu = self.s3.create_multipart_upload(Bucket=self.bucket, Key=self.key)
        self.multipart_id = mpu["UploadId"]

        # create a multipart info file
        with open(self.multipart_info_file_path, "w+", encoding="utf8") as multipart_info_file:
            multipart_info_file.write(
                json.dumps(
                    {
                        "multipart_id": self.multipart_id,
                        "current_part_number": 1,
                        "file": self.file_path,
                        "total_bytes": os.stat(self.file_path).st_size,
                        "uploaded_bytes": 0,
                        "part_size": self.part_size_bytes,
                        "parts": [],
                    }
                )
            )
            multipart_info_file.flush()

    def _complete(self, multipart_id: str, parts: List[dict]):
        try:
            result = self.s3.complete_multipart_upload(
                Bucket=self.bucket,
                Key=self.key,
                UploadId=multipart_id,
                MultipartUpload={"Parts": parts},
            )

            res_length = result.get("ResponseMetadata", {}).get("HTTPHeaders", {}).get("content-length", 0)
            req_length = len(json.dumps(parts))
            request_hook.increase_upload_bytes(req_length)
            request_hook.increase_download_bytes(int(res_length))
        except EndpointConnectionError as e:
            raise ConnectionError(f"Cannot complete the upload due to connectivity problem - {str(e)}")

        # os.remove(self.multipart_info_file_path)
        self.stop_event.set()

        return result

    def upload(self):
        if not Path(self.file_path).exists():
            _log.warning(f"==> File {self.file_path} not found")
            return

        parts = []
        uploaded_bytes = 0
        curr_part_num = 1

        # initialize multipart on first time
        if not os.path.isfile(self.multipart_info_file_path):
            self._create()

        self.stop_event.clear()

        with open(self.multipart_info_file_path, "r+", encoding="utf8") as multipart_info_file:
            # get current part number
            multipart_info = json.load(multipart_info_file)
            starting_part_num = multipart_info["current_part_number"]
            uploaded_bytes = multipart_info["uploaded_bytes"]
            parts = multipart_info["parts"]
            multipart_id = multipart_info["multipart_id"]
            file_total_bytes = multipart_info["total_bytes"]

            # calc how many parts are there to upload
            total_parts = (file_total_bytes + self.part_size_bytes - 1) // self.part_size_bytes

            with open(self.file_path, "rb") as file_to_upload:
                # seek to previous position
                if starting_part_num > 1:
                    file_to_upload.seek((starting_part_num - 1) * self.part_size_bytes)

                for curr_part_num in range(starting_part_num, total_parts + 1):
                    # stop if someone ordered the upload process to stop
                    if self.stop_event.is_set():
                        break

                    data = file_to_upload.read(self.part_size_bytes)
                    if not len(data):
                        break

                    # upload current part
                    try:
                        part = self.s3.upload_part(
                            Body=data,
                            Bucket=self.bucket,
                            Key=self.key,
                            UploadId=multipart_id,
                            PartNumber=curr_part_num,
                        )
                    except EndpointConnectionError as e:
                        raise ConnectionError(f"Connection problem while uploading part {curr_part_num} - {str(e)}")

                    parts.append({"PartNumber": curr_part_num, "ETag": part["ETag"]})
                    uploaded_bytes += len(data)

                    res_length = part.get("ResponseMetadata", {}).get("HTTPHeaders", {}).get("content-length", 0)
                    request_hook.increase_upload_bytes(uploaded_bytes)
                    request_hook.increase_download_bytes(int(res_length))

                    # update info file
                    multipart_info.update({"current_part_number": curr_part_num + 1})
                    multipart_info.update({"uploaded_bytes": uploaded_bytes})
                    multipart_info.update({"parts": parts})

                    multipart_info_file.seek(0)
                    multipart_info_file.truncate(0)
                    multipart_info_file.write(json.dumps(multipart_info))
                    multipart_info_file.flush()

                    _log.info(f"==> Uploaded part {curr_part_num}/{total_parts} - {tools.size_fmt(uploaded_bytes)}")

        if curr_part_num == total_parts:
            self._complete(multipart_id, parts)
            _log.info(f"==> Upload file {self.file_path} completed")

    def pause_current_upload(self):
        """
        Stops the current upload process. Takes effect on the next part.
        """
        self.stop_event.set()

    def abort(self):
        """
        Completely cancels the current uploading process and deletes all resources that related to this upload from the bucket.
        """
        with open(self.multipart_info_file_path, "r+") as multipart_info_file:
            multipart_info = json.load(multipart_info_file)
            self.s3.abort_multipart_upload(Bucket=self.bucket, Key=self.key, UploadId=multipart_info["multipart_id"])

    @staticmethod
    def abort_all_bucket_multipart_uploads(s3: boto3.client, bucket_name: str):
        aborted = []
        mpus = s3.list_multipart_uploads(Bucket=bucket_name)

        if "Uploads" in mpus:
            for u in mpus["Uploads"]:
                upload_id = u["UploadId"]
                aborted.append(s3.abort_multipart_upload(Bucket=bucket_name, Key=u["Key"], UploadId=upload_id))

        return aborted
