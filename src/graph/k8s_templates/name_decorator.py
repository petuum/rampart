# Copyright 2023 Petuum, Inc. All Rights Reserved.

from ..objects.base_types import KubernetesName


def use_kubernetes_name(fun):
    def wrapper(name, namespace, *args, **kwargs):
        if isinstance(name, KubernetesName):
            name = name.kubernetes_view
        if isinstance(namespace, KubernetesName):
            namespace = namespace.kubernetes_view
        return fun(name, namespace, *args, **kwargs)
    return wrapper
