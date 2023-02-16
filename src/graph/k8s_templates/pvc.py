# Copyright 2023 Petuum, Inc. All Rights Reserved.

from .name_decorator import use_kubernetes_name


@use_kubernetes_name
def pvc_template(claim_name, namespace, storage_class, storage_volume):
    return {
        "kind": "PersistentVolumeClaim",
        "apiVersion": "v1",
        "metadata": {
            "name": claim_name,
            "namespace": namespace,
        },
        "spec": {
            "storageClassName": storage_class,
            "accessModes": ["ReadWriteMany"],
            "resources": {
                "requests": {
                    "storage": storage_volume
                }
            }
        }
    }
