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

import base64
from kubernetes_asyncio import client as k8s_client
from .classes import DeploymentError
from ..k8s_templates import image_pull_secret_template

core_api = k8s_client.CoreV1Api()


async def create_secret_by_filepath(secret_name, namespace, filepath):
    """
    Creates a kubernetes secret from a file on the same container as the
    rampart controller. Used to create imagepullsecrets to pull
    Rampart images for the components.
    """
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
