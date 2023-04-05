# Copyright 2023 Petuum, Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License."

from .name_decorator import use_kubernetes_name


@use_kubernetes_name
def config_map_template(name, namespace, body):
    return {
        "kind": "ConfigMap",
        "apiVersion": "v1",
        "metadata": {"name": name,
                     "namespace": namespace},
        "data": body
        }


def config_map_mount(name, mounts, mount_path):
    return {
        "spec": {
            "podTemplate": {
                "volumes": [{
                    "name": name,
                    "configMap": {
                        "name": name,
                        "items": [{"key": key, "path": path} for key, path in mounts.items()]
                        }
                    }]},
            "containerTemplate":
                {"volumeMounts": [{
                    "name": name,
                    "mountPath": mount_path,
                    "readOnly": True}]}
            }
        }
