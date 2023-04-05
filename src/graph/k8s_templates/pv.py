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

from ..objects.base_types import KubernetesName


def pv_template(volume_name, claim_name, claim_namespace, storage_class, storage_volume, access):
    if isinstance(volume_name, KubernetesName):
        volume_name = volume_name.kubernetes_view
    if isinstance(claim_name, KubernetesName):
        claim_name = claim_name.kubernetes_view
    if isinstance(claim_namespace, KubernetesName):
        claim_namespace = claim_namespace.kubernetes_view
    return {
        "kind": "PersistentVolume",
        "apiVersion": "v1",
        "metadata": {
            "name": volume_name,
        },
        "spec": {
            "storageClassName": storage_class,
            "claimRef": {
                "name": claim_name,
                "namespace": claim_namespace
            },
            "capacity": {
                "storage": storage_volume,
            },
            "volumeMode": "Filesystem",
            "accessModes": access,
        }
    }
