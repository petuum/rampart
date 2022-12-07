# Copyright 2023 Petuum, Inc. All Rights Reserved.

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
