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

from pydantic import BaseModel


class RecordName(BaseModel):
    name: str
    warehouse_id: str | None
    project_id: str
    record_id: str

    @staticmethod
    def from_str(record_name: str):
        # record_name: warehouses/xxx/projects/xxx/records/xxx or projects/xxx/records/xxx
        # name: xxx, warehouse_id: xxx, project_id: xxx, record_id: xxx
        if record_name.startswith("projects/"):
            parts = record_name.split("/")
            if len(parts) != 4 or parts[2] != "records":
                raise ValueError(f"Invalid path format for record name: {record_name}")
            return RecordName(name=record_name, warehouse_id=None, project_id=parts[1], record_id=parts[3])
        else:
            parts = record_name.split("/")
            if len(parts) != 6 or parts[0] != "warehouses" or parts[2] != "projects" or parts[4] != "records":
                raise ValueError(f"Invalid path format for record name: {record_name}")

            warehouse_id = parts[1]
            project_id = parts[3]
            record_id = parts[5]

            # Assuming the 'name' attribute should be derived from 'record_id' or similar.
            # If it's different, you'll need to adjust the logic accordingly.
            name = record_name
            return RecordName(name=name, warehouse_id=warehouse_id, project_id=project_id, record_id=record_id)

    def simple_record_name(self):
        return f"projects/{self.project_id}/records/{self.record_id}"
