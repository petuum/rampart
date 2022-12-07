# Copyright 2023 Petuum, Inc. All Rights Reserved.

from .name_decorator import use_kubernetes_name


@use_kubernetes_name
def infra_template(name, namespace, provides):
    return {
        "kind": "RampartInfra",
        "apiVersion": "rampart.petuum.com/v1beta1",
        "metadata": {"name": name,
                     "namespace": namespace},
        "spec": {
            "provides": [{"name": infra} for infra in provides]
        }
    }
