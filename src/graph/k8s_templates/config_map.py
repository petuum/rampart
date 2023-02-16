# Copyright 2023 Petuum, Inc. All Rights Reserved.

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
