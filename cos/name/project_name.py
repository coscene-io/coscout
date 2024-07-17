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


class ProjectName(BaseModel):
    name: str
    warehouse_id: str | None
    project_id: str

    @staticmethod
    def from_str(project_name: str):
        # record_name: warehouses/xxx/projects/xxx or projects/xxx
        # name: xxx, warehouse_id: xxx, project_id: xxx
        if project_name.startswith("projects/"):
            parts = project_name.split("/")
            if len(parts) != 2:
                raise ValueError("Invalid path format for project name")
            return ProjectName(name=project_name, warehouse_id=None, project_id=parts[1])
        else:
            parts = project_name.split("/")
            if len(parts) != 4 or parts[0] != "warehouses" or parts[2] != "projects":
                raise ValueError("Invalid path format for project name")

            warehouse_id = parts[1]
            project_id = parts[3]

            # Assuming the 'name' attribute should be derived from 'record_id' or similar.
            # If it's different, you'll need to adjust the logic accordingly.
            name = project_name
            return ProjectName(name=name, warehouse_id=warehouse_id, project_id=project_id)

    @staticmethod
    def with_warehouse_and_project_id(warehouse_id: str, project_id: str):
        if not warehouse_id:
            return ProjectName(name=f"projects/{project_id}", warehouse_id=None, project_id=project_id)
        return ProjectName(
            name=f"warehouses/{warehouse_id}/projects/{project_id}", warehouse_id=warehouse_id, project_id=project_id
        )
