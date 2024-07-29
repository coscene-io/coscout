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

import base64
import logging
from typing import List, Dict

import grpc
from coscene.openapi.datastorage.v1alpha1.services import security_token_pb2, security_token_pb2_grpc
from coscene.openapi.dataplatform.v1alpha1.services import (
    organization_pb2_grpc,
    organization_pb2,
    project_pb2_grpc,
    project_pb2,
    record_pb2,
    task_pb2,
    task_pb2_grpc,
    label_pb2,
    label_pb2_grpc,
    device_pb2,
    device_pb2_grpc,
    record_pb2_grpc,
    config_map_pb2,
    config_map_pb2_grpc,
    diagnosis_rule_pb2,
    diagnosis_rule_pb2_grpc,
    event_pb2,
    event_pb2_grpc,
)
from coscene.openapi.dataplatform.v1alpha1.resources import (
    record_pb2 as record_pb2_resource,
    task_pb2 as task_pb2_resource,
    label_pb2 as label_pb2_resource,
    device_pb2 as device_pb2_resource,
    event_pb2 as event_pb2_resource,
)
from coscene.openapi.dataplatform.v1alpha1.enums import task_category_pb2

from google.protobuf import json_format, field_mask_pb2, duration_pb2, timestamp_pb2
from google.rpc.code_pb2 import UNAUTHENTICATED

from cos.core import request_hook
from cos.core.api import ApiClient, ApiClientConfig
from cos.core.exceptions import Unauthorized, CosException

_log = logging.getLogger(__name__)


class BasicTokenAuthMetadataPlugin(grpc.AuthMetadataPlugin):
    def __init__(self, access_token: str):
        self._access_token = access_token

    def __call__(self, context, callback):
        metadata = (("authorization", self._access_token),)
        callback(metadata, None)


class NetworkUsageInterceptor(grpc.UnaryUnaryClientInterceptor):
    def intercept_unary_unary(self, continuation, client_call_details, request):
        request_size = request.ByteSize()
        _log.debug(f"Sending request of size: {request_size} bytes")
        request_hook.increase_upload_bytes(request_size)

        response_future = continuation(client_call_details, request)
        if grpc.StatusCode.OK == response_future.code():
            response_size = response_future.result().ByteSize()
            _log.debug(f"Received response of size: {response_size} bytes")
            request_hook.increase_download_bytes(response_size)
        return response_future


class GrpcClient(ApiClient):
    def __init__(self, conf: ApiClientConfig):
        super().__init__(conf)
        self._api_key = self.state.api_key
        self._conf = conf

        self._channel = self.__create_client_channel(self.__get_address(), self.__get_basic_token("apikey", self._api_key))

    def __get_address(self):
        url = self._conf.server_url.removeprefix("https://").removeprefix("http://")
        return url

    def __get_basic_token(self, username: str, password: str):
        userpass = username + ":" + password
        encoded_u = base64.b64encode(userpass.encode()).decode()
        return "Basic %s" % encoded_u

    def __create_client_channel(self, addr: str, token: str):
        call_credentials = grpc.metadata_call_credentials(BasicTokenAuthMetadataPlugin(token), name="basic_token_auth")
        channel_credential = grpc.ssl_channel_credentials()
        composite_credentials = grpc.composite_channel_credentials(
            channel_credential,
            call_credentials,
        )

        interceptors = [NetworkUsageInterceptor()]
        channel = grpc.secure_channel(addr, composite_credentials)
        intercept_channel = grpc.intercept_channel(channel, *interceptors)
        return intercept_channel

    def get_organization(self):
        try:
            stub = organization_pb2_grpc.OrganizationServiceStub(self._channel)
            req = organization_pb2.GetOrganizationRequest(name="organizations/current")
            res = stub.GetOrganization(req, timeout=10)
            result = json_format.MessageToDict(res)
            _log.info("==> Get the organization {org_name}".format(org_name=result.get("name")))
            return result
        except grpc.RpcError as rpc_error:
            _log.error("Get the organization failure: %s", rpc_error)
            raise RuntimeError("Failed to get organization")

    def get_configmap(self, config_key, parent_name):
        try:
            stub = config_map_pb2_grpc.ConfigMapServiceStub(self._channel)

            parent = parent_name or self.org_name
            req = config_map_pb2.GetConfigMapRequest(name=f"{parent}/configMaps/{config_key}")
            res = stub.GetConfigMap(req, timeout=10)

            result = json_format.MessageToDict(res)
            _log.info("==> Get the config map: {config_key}".format(config_key=config_key))
            return result
        except grpc.RpcError as rpc_error:
            _log.error("Get the config map failure: %s", rpc_error)
            raise RuntimeError("Failed to get config map")

    def get_configmap_metadata(self, config_key, parent_name):
        try:
            stub = config_map_pb2_grpc.ConfigMapServiceStub(self._channel)

            parent = parent_name or self.org_name
            req = config_map_pb2.GetConfigMapMetadataRequest(name=f"{parent}/configMaps/{config_key}")
            res = stub.GetConfigMapMetadata(req, timeout=10)

            result = json_format.MessageToDict(res)
            _log.info("==> Get the config map metadata: {config_key}".format(config_key=config_key))
            return result
        except grpc.RpcError as rpc_error:
            _log.error("Get the config map metadata failure: %s", rpc_error)
            raise RuntimeError("Failed to get config map metadata")

    def list_device_projects(self, device_name: str) -> List[Dict]:
        try:
            req = project_pb2.ListDeviceProjectsRequest(parent=device_name, page_size=100, order_by="create_time asc")
            stub = project_pb2_grpc.ProjectServiceStub(self._channel)
            res = stub.ListDeviceProjects(req, timeout=10)

            return [json_format.MessageToDict(proj) for proj in res.device_projects]
        except grpc.RpcError as rpc_error:
            _log.error("Get device projects failure: %s", rpc_error)
            raise RuntimeError("Failed to get device projects")

    def project_slug_to_name(self, proj_slug: str):
        try:
            name = "projects/%s" % (proj_slug.split("/")[-1])
            req = project_pb2.GetProjectRequest(name=name)
            stub = project_pb2_grpc.ProjectServiceStub(self._channel)
            res = stub.GetProject(req, timeout=10)

            return res.name
        except grpc.RpcError as rpc_error:
            _log.error("Get the organization failure: %s", rpc_error)
            raise RuntimeError("Failed to get project name")

    def create_record(self, file_infos, title="Untitled", description="", labels=None, device_name=None):
        try:
            device = device_pb2_resource.Device()
            if device_name:
                device = device_pb2_resource.Device(name=device_name)

            req = record_pb2.CreateRecordRequest(
                parent=self.project_name,
                record=record_pb2_resource.Record(
                    title=title,
                    description=description,
                    labels=[self.ensure_label(lbl) for lbl in labels or []],
                    device=device,
                ),
            )

            stub = record_pb2_grpc.RecordServiceStub(self._channel)
            res = stub.CreateRecord(req, timeout=10)
            return json_format.MessageToDict(res)
        except grpc.RpcError as rpc_error:
            _log.error("create record failure: %s", rpc_error)
            if UNAUTHENTICATED == rpc_error.code():
                raise Unauthorized("Unauthorized")
            raise RuntimeError("Failed to create record")

    def update_record(self, record_name, title=None, description="", labels=None) -> dict:
        try:
            update_labels = [self.ensure_label(lbl) for lbl in labels or []]
            update_mask = field_mask_pb2.FieldMask(paths=[])
            record = record_pb2_resource.Record(name=record_name, labels=update_labels)
            if title:
                record.title = title
                update_mask.paths.append("title")
            if description:
                record.description = description
                update_mask.paths.append("description")
            if labels:
                update_mask.paths.append("labels")

            req = record_pb2.UpdateRecordRequest(record=record, update_mask=update_mask)
            stub = record_pb2_grpc.RecordServiceStub(self._channel)
            res = stub.UpdateRecord(req, timeout=10)

            return json_format.MessageToDict(res)
        except grpc.RpcError as rpc_error:
            _log.error("update record failure: %s", rpc_error)
            if UNAUTHENTICATED == rpc_error.code():
                raise Unauthorized("Unauthorized")
            raise RuntimeError("Failed to update record")

    def get_record(self, record_name: str) -> dict:
        try:
            req = record_pb2.GetRecordRequest(name=record_name)
            stub = record_pb2_grpc.RecordServiceStub(self._channel)
            res = stub.GetRecord(req, timeout=10)

            return json_format.MessageToDict(res)
        except grpc.RpcError as rpc_error:
            _log.error("get record failure: %s", rpc_error)
            if UNAUTHENTICATED == rpc_error.code():
                raise Unauthorized("Unauthorized")
            raise RuntimeError("Failed to get record")

    def generate_record_thumbnail_upload_url(self, record_name: str, expire_duration: int = 3600):
        try:
            req = record_pb2.GenerateRecordThumbnailUploadUrlRequest(
                record=record_name,
                expire_duration=duration_pb2.Duration(seconds=expire_duration),
            )
            stub = record_pb2_grpc.RecordServiceStub(self._channel)
            res = stub.GenerateRecordThumbnailUploadUrl(req, timeout=10)

            _log.info(f"==> Generated thumbnail upload url for {record_name}")
            return res.pre_signed_uri
        except grpc.RpcError as rpc_error:
            _log.error("Generated thumbnail upload url failure: %s", rpc_error)
            if UNAUTHENTICATED == rpc_error.code():
                raise Unauthorized("Unauthorized")
            raise RuntimeError("Failed to generate a thumbnail upload url")

    def get_device(self, device_name: str) -> dict:
        try:
            req = device_pb2.GetDeviceRequest(name=device_name)
            stub = device_pb2_grpc.DeviceServiceStub(self._channel)
            res = stub.GetDevice(req, timeout=10)

            _log.info("==> Get the device {device_name}".format(device_name=res.name))
            return json_format.MessageToDict(res)
        except grpc.RpcError as rpc_error:
            _log.error("get device failure: %s", rpc_error)
            if UNAUTHENTICATED == rpc_error.code():
                raise Unauthorized("Unauthorized")
            raise RuntimeError("Failed to get device")

    def update_device_tags(self, device_name: str, tags: dict) -> None:
        try:
            req = device_pb2.AddDeviceTagRequest(device=device_name, tags=tags)
            stub = device_pb2_grpc.DeviceServiceStub(self._channel)
            stub.AddDeviceTag(req, timeout=10)
        except grpc.RpcError as rpc_error:
            _log.error("add device tags failure: %s", rpc_error)
            if UNAUTHENTICATED == rpc_error.code():
                raise Unauthorized("Unauthorized")
            raise RuntimeError("Failed to get device")

    def register_device(self, serial_number=None, display_name=None, description=None, labels=None, tags=None) -> dict | None:
        if not serial_number:
            return None

        try:
            req = device_pb2.RegisterDeviceRequest(
                device=device_pb2_resource.Device(
                    serial_number=serial_number,
                    display_name=display_name or serial_number,
                    description=description,
                    labels=labels,
                    tags=tags,
                )
            )
            if self._project_slug:
                req.project_slug = self._project_slug
            if self._org_slug:
                req.organization_slug = self._org_slug

            stub = device_pb2_grpc.DeviceServiceStub(self._channel)
            res = stub.RegisterDevice(req, timeout=10)

            if not res.device or not res.exchange_code or not res.device.name:
                raise CosException(f"Failed to register device {serial_number}, reso is {res}")

            _log.info("==> register the device {sn}".format(sn=serial_number))
            return json_format.MessageToDict(res)
        except grpc.RpcError as rpc_error:
            _log.error("Exchange the device auth token failure: %s", rpc_error)
            if UNAUTHENTICATED == rpc_error.code():
                raise Unauthorized("Unauthorized")
            raise RuntimeError("Failed to exchange the device auth token")

    def exchange_device_auth_token(self, device_name: str, code: str) -> dict | None:
        if not device_name or not code:
            return None
        try:
            req = device_pb2.ExchangeDeviceAuthTokenRequest(
                device=device_name,
                exchange_code=code,
            )

            stub = device_pb2_grpc.DeviceServiceStub(self._channel)
            res = stub.ExchangeDeviceAuthToken(req, timeout=10)

            return json_format.MessageToDict(res)
        except grpc.RpcError as rpc_error:
            _log.error("Exchange the device auth token failure: %s", rpc_error)
            if UNAUTHENTICATED == rpc_error.code():
                raise Unauthorized("Unauthorized")
            raise RuntimeError("Failed to exchange the device auth token")

    def check_device_status(self, device_name: str, code: str) -> dict:
        try:
            req = device_pb2.CheckDeviceStatusRequest(
                device=device_name,
                exchange_code=code,
            )

            stub = device_pb2_grpc.DeviceServiceStub(self._channel)
            res = stub.CheckDeviceStatus(req, timeout=10)

            return json_format.MessageToDict(res)
        except grpc.RpcError as rpc_error:
            _log.error("check device status failure: %s", rpc_error)
            if UNAUTHENTICATED == rpc_error.code():
                raise Unauthorized("Unauthorized")
            raise RuntimeError("Failed to check device status")

    def send_heartbeat(self, device_name: str, cos_version: str, network_usage: dict) -> None:
        try:
            stub = device_pb2_grpc.DeviceServiceStub(self._channel)

            req = device_pb2.HeartbeatDeviceRequest(
                name=device_name,
                cos_version=cos_version,
                network_usage=device_pb2.NetworkUsage(
                    upload_bytes=network_usage.get("upload_bytes", 0),
                    download_bytes=network_usage.get("download_bytes", 0),
                ),
            )
            stub.HeartbeatDevice(req, timeout=10)
        except grpc.RpcError as rpc_error:
            _log.error("Device heartbeat failure: %s", rpc_error)
            raise RuntimeError("Failed to send device heartbeat")

    def create_event(
        self,
        record_name: str,
        display_name: str,
        trigger_time: float,
        description: str,
        customized_fields: dict,
        device_name: str,
        duration: float,
    ) -> dict:
        try:
            req = event_pb2.ObtainEventRequest(
                parent=self.project_name,
                event=event_pb2_resource.Event(
                    record=record_name,
                    display_name=display_name,
                    trigger_time=timestamp_pb2.Timestamp(seconds=int(trigger_time), nanos=int(trigger_time % 1 * 1e9)),
                    description=description,
                    customized_fields=customized_fields or {},
                    device=device_pb2_resource.Device(name=device_name),
                    duration=duration_pb2.Duration(seconds=int(duration), nanos=int(duration % 1 * 1e9)),
                ),
            )

            stub = event_pb2_grpc.EventServiceStub(self._channel)
            res = stub.ObtainEvent(req, timeout=10)

            result = json_format.MessageToDict(res.event)
            _log.info("==> Created the event {event_name}".format(event_name=result.get("displayName", "")))
            return result
        except grpc.RpcError as rpc_error:
            _log.error("obtain event failure: %s", rpc_error)
            if UNAUTHENTICATED == rpc_error.code():
                raise Unauthorized("Unauthorized")
            raise RuntimeError("Failed to obtain event")

    def generate_security_token(self, project_name: str, ttl_hash: int = 3600) -> dict:
        _log.info("==> Generating security token")

        try:
            req = security_token_pb2.GenerateSecurityTokenRequest(
                project=project_name, expire_duration=duration_pb2.Duration(seconds=ttl_hash)
            )

            stub = security_token_pb2_grpc.SecurityTokenServiceStub(self._channel)
            res = stub.GenerateSecurityToken(req, timeout=10)

            _log.info("==> Generated security token")
            return json_format.MessageToDict(res)
        except grpc.RpcError as rpc_error:
            _log.error("generate security token failure: %s", rpc_error)
            if UNAUTHENTICATED == rpc_error.code():
                raise Unauthorized("Unauthorized")
            raise RuntimeError("Failed to generate security token")

    def create_label(self, display_name) -> label_pb2_resource.Label:
        try:
            req = label_pb2.CreateLabelRequest(
                parent=self.project_name,
                label=label_pb2_resource.Label(display_name=display_name),
            )

            stub = label_pb2_grpc.LabelServiceStub(self._channel)
            res = stub.CreateLabel(req, timeout=10)

            return res
        except grpc.RpcError as rpc_error:
            _log.error("create label failure: %s", rpc_error)
            if UNAUTHENTICATED == rpc_error.code():
                raise Unauthorized("Unauthorized")
            raise RuntimeError("Failed to create label")

    def get_label_by_display_name(self, display_name: str) -> label_pb2_resource.Label:
        try:
            req = label_pb2.ListLabelsRequest(
                parent=self.project_name,
                filter=f'displayName="{display_name}"',
                page_size=100,
            )

            stub = label_pb2_grpc.LabelServiceStub(self._channel)
            res = stub.ListLabels(req, timeout=10)

            for label in res.labels:
                if label.display_name == display_name:
                    return label
            return label_pb2_resource.Label()
        except grpc.RpcError as rpc_error:
            _log.error("get label failure: %s", rpc_error)
            if UNAUTHENTICATED == rpc_error.code():
                raise Unauthorized("Unauthorized")
            raise RuntimeError("Failed to get label")

    def get_label(self, label_name: str) -> dict:
        try:
            req = label_pb2.GetLabelRequest(name=label_name)

            stub = label_pb2_grpc.LabelServiceStub(self._channel)
            res = stub.GetLabel(req, timeout=10)

            return json_format.MessageToDict(res)
        except grpc.RpcError as rpc_error:
            _log.error("get label failure: %s", rpc_error)
            if UNAUTHENTICATED == rpc_error.code():
                raise Unauthorized("Unauthorized")
            raise RuntimeError("Failed to get label")

    def ensure_label(self, display_name) -> dict:
        label = self.get_label_by_display_name(display_name)
        if not label:
            label = self.create_label(display_name)
        return label

    def counter(self, name, value=1, description=None, extra_labels=None):
        _log.debug(f"==> Counter not implemented: {name}={value}")

    def timer(self, name, value, description=None, extra_labels=None):
        _log.debug(f"==> Timer not implemented: {name}={value}")

    def gauge(self, name, value, description=None, extra_labels=None):
        _log.debug(f"==> Gauge not implemented: {name}={value}")

    def hit_diagnosis_rule(self, diagnosis_rule, hit, device, upload) -> None:
        try:
            req = diagnosis_rule_pb2.HitDiagnosisRuleRequest(
                diagnosis_rule=diagnosis_rule.get("name", ""), hit=hit, device=device, upload=upload
            )
            stub = diagnosis_rule_pb2_grpc.DiagnosisServiceStub(self._channel)
            stub.HitDiagnosisRule(req, timeout=10)

            _log.info(
                "==> Successfully hit diagnosis rule for {diagnosis_rule}".format(
                    diagnosis_rule=diagnosis_rule.get("name", "")
                )
            )
        except grpc.RpcError as rpc_error:
            _log.error("count diagnosis rule failure: %s", rpc_error)
            if UNAUTHENTICATED == rpc_error.code():
                raise Unauthorized("Unauthorized")
            raise RuntimeError("Failed to count diagnosis rule")

    def count_diagnosis_rules_hit(self, diagnosis_rule, hit, device) -> dict:
        try:
            req = diagnosis_rule_pb2.CountDiagnosisRuleHitsRequest(diagnosis_rule=diagnosis_rule, hit=hit, device=device)
            stub = diagnosis_rule_pb2_grpc.DiagnosisServiceStub(self._channel)
            res = stub.CountDiagnosisRuleHits(req, timeout=10)

            result = json_format.MessageToDict(res)
            _log.info("==> Fetched diagnosis rule hit counts for {diagnosis_rule}".format(diagnosis_rule=diagnosis_rule))
            return result
        except grpc.RpcError as rpc_error:
            _log.error("count diagnosis rule failure: %s", rpc_error)
            if UNAUTHENTICATED == rpc_error.code():
                raise Unauthorized("Unauthorized")
            raise RuntimeError("Failed to count diagnosis rule")

    def get_diagnosis_rules_metadata(self, parent_name: str = None) -> dict:
        try:
            parent = "projects/-" if not parent_name else parent_name

            req = diagnosis_rule_pb2.GetDiagnosisRuleMetadataRequest(name=f"{parent}/diagnosisRule")
            stub = diagnosis_rule_pb2_grpc.DiagnosisServiceStub(self._channel)
            res = stub.GetDiagnosisRuleMetadata(req, timeout=10)

            result = json_format.MessageToDict(res)
            _log.info("==> Fetched the diagnosis rules metadata {result}".format(result=result.get("name")))
            return result
        except grpc.RpcError as rpc_error:
            _log.error("get diagnosis rule metadata failure: %s", rpc_error)
            if UNAUTHENTICATED == rpc_error.code():
                raise Unauthorized("Unauthorized")
            raise RuntimeError("Failed to get diagnosis rule metadata")

    def get_diagnosis_rule(self, parent_name: str = None) -> dict:
        try:
            parent = "projects/-" if not parent_name else parent_name

            req = diagnosis_rule_pb2.GetDiagnosisRuleRequest(name=f"{parent}/diagnosisRule")
            stub = diagnosis_rule_pb2_grpc.DiagnosisServiceStub(self._channel)
            res = stub.GetDiagnosisRule(req, timeout=10)

            result = json_format.MessageToDict(res)
            _log.info("==> Fetched the diagnosis rules {result}".format(result=result.get("name")))
            return result
        except grpc.RpcError as rpc_error:
            _log.error("get diagnosis rule failure: %s", rpc_error)
            if UNAUTHENTICATED == rpc_error.code():
                raise Unauthorized("Unauthorized")
            raise RuntimeError("Failed to get diagnosis rule")

    def create_task(self, record_name: str, title: str, description: str, assignee: str | None) -> dict:
        try:
            init_task = task_pb2_resource.Task(
                title=title,
                description=description,
                category=task_category_pb2.TaskCategoryEnum.COMMON,
                common_task_detail=task_pb2_resource.CommonTaskDetail(
                    record=record_name,
                ),
            )
            if assignee:
                init_task.assignee = assignee

            req = task_pb2.CreateTaskRequest(parent=self.project_name, task=init_task)
            stub = task_pb2_grpc.TaskServiceStub(self._channel)
            res = stub.CreateTask(req, timeout=10)

            return json_format.MessageToDict(res)
        except grpc.RpcError as rpc_error:
            _log.error("create task failure: %s", rpc_error)
            if UNAUTHENTICATED == rpc_error.code():
                raise Unauthorized("Unauthorized")
            raise RuntimeError("Failed to update task state")

    def list_device_tasks(self, device_name: str, filter_state: str = None) -> List[Dict]:
        try:
            filter_state = "TASK_STATE_UNSPECIFIED" if not filter_state else filter_state
            filter_str = f'state="{filter_state}"'

            req = task_pb2.ListDeviceTasksRequest(parent=device_name, filter=filter_str, page_size=10)
            stub = task_pb2_grpc.TaskServiceStub(self._channel)
            res = stub.ListDeviceTasks(req, timeout=10)

            return [json_format.MessageToDict(task) for task in res.device_tasks]
        except grpc.RpcError as rpc_error:
            _log.error("list tasks failure: %s", rpc_error)
            if UNAUTHENTICATED == rpc_error.code():
                raise Unauthorized("Unauthorized")
            raise RuntimeError("Failed to list tasks")

    def update_task_state(self, task_name: str, state: str) -> None:
        try:
            req = task_pb2.UpdateTaskRequest(
                task=task_pb2_resource.Task(name=task_name, state=state),
                update_mask=field_mask_pb2.FieldMask(paths=["state"]),
            )
            stub = task_pb2_grpc.TaskServiceStub(self._channel)
            stub.UpdateTask(req, timeout=10)
        except grpc.RpcError as rpc_error:
            _log.error("update task state failure: %s", rpc_error)
            if UNAUTHENTICATED == rpc_error.code():
                raise Unauthorized("Unauthorized")
            raise RuntimeError("Failed to update task state")

    def put_task_tags(self, task_name: str, tags: dict) -> None:
        try:
            req = task_pb2.AddTaskTagsRequest(
                task=task_name,
                tags=tags,
            )
            stub = task_pb2_grpc.TaskServiceStub(self._channel)
            stub.AddTaskTags(req, timeout=10)
        except grpc.RpcError as rpc_error:
            _log.error("put task tags failure: %s", rpc_error)
            if UNAUTHENTICATED == rpc_error.code():
                raise Unauthorized("Unauthorized")
            raise RuntimeError("Failed to put task tags")
