# Copyright 2023 Petuum, Inc. All Rights Reserved.

from .name_decorator import use_kubernetes_name


@use_kubernetes_name
def preset_template(name, namespace):
    return {
        "kind": "MutationPreset",
        "apiVersion": "rampart.petuum.com/v1beta1",
        "metadata": {"name": name,
                     "namespace": namespace,
                     "annotations": {
                         "helm.sh/hook": "pre-install,pre-upgrade",
                         "helm.sh/hook-weight": "-5"}},
        "spec": {
            "containerTemplate": {},
            "podTemplate": {}
        }
    }
