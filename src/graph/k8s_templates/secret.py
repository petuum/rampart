# Copyright 2023 Petuum, Inc. All Rights Reserved.

import kubernetes_asyncio.client as client
from ..objects.base_types import KubernetesName


def image_pull_secret_template(name, dockerconfigjson, to_dict=False):
    if isinstance(name, KubernetesName):
        name = name.kubernetes_view
    if not to_dict:
        return client.V1Secret(
            metadata=client.V1ObjectMeta(name=name),
            type="kubernetes.io/dockerconfigjson",
            data={
                ".dockerconfigjson": dockerconfigjson
            }
        )
    else:
        return {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": name},
            "type": "kubernetes.io/dockerconfigjson",
            "data": {
                ".dockerconfigjson": dockerconfigjson
            }
        }
