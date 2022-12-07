# Copyright 2023 Petuum, Inc. All Rights Reserved.

import base64
from kubernetes_asyncio import client as k8s_client
from .classes import DeploymentError
from ..k8s_templates import image_pull_secret_template

core_api = k8s_client.CoreV1Api()


async def create_secret_by_filepath(secret_name, namespace, filepath):
    try:
        with open(filepath, "rb") as f:
            dockerconfigjson = str(base64.b64encode(f.read()), "utf-8")
    except FileNotFoundError:
        raise DeploymentError(
            {"Image pull secret path is given but file does not exist. "
             "This is a Rampart controller error; please report this bug."})
    secret = image_pull_secret_template(secret_name, dockerconfigjson)
    try:
        await core_api.create_namespaced_secret(namespace, body=secret)
    except k8s_client.rest.ApiException as e:
        if e.reason == "Conflict":
            await core_api.patch_namespaced_secret(secret_name, namespace, body=secret)
        else:
            raise DeploymentError({str(e)})
