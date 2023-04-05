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

from base64 import b64decode
import kubernetes_asyncio as kubernetes

from .base_types import BaseElement, Metadata, KubernetesName
from ..utils.classes import SubprocessArgs, ValidationError
from ..utils.deployment import require_validated


kubernetes.config.load_incluster_config()
core_api = kubernetes.client.CoreV1Api()


class Secret(BaseElement):
    """
    Represents username and password for connecting to remote helm repositories, stored using
    a kubernetes secret.
    """
    def __init__(self, namespace, name):
        metadata = Metadata(namespace, name, None)
        super().__init__(metadata)
        self._username = None
        self._password = None

    @require_validated
    async def deploy(self):
        pass

    async def validate(self):
        """
        Raises a `ValidationError` if the secret is invalid. This call must be made
        before any function with the `@required_validated` decorator is called.

        Raises:
            ValidationError: If the secret is invalid
        """
        if isinstance(self.name, KubernetesName):
            name = self.name.kubernetes_view
        else:
            name = self.name
        if isinstance(self.namespace, KubernetesName):
            namespace = self.namespace.kubernetes_view
        else:
            namespace = self.namespace
        try:
            secret = await core_api.read_namespaced_secret(name, namespace)
        except kubernetes.client.rest.ApiException as exc:
            if exc.status == 404:
                raise ValidationError({f"Secret {namespace}/{name} not found"})
        # TODO: move all of this to validate
        errors = []
        if not secret.data:
            raise ValidationError({f'Cannot find data in secret {namespace}/{name}'})

        if "username" not in secret.data:
            errors.append(f'Key "username" not found in secret {namespace/name}')
        if "password" not in secret.data:
            errors.append(f'Key "password" not found in secret {namespace/name}')
        if errors:
            raise ValidationError(errors)
        username = b64decode(secret.data["username"]).decode("utf-8")
        password = b64decode(secret.data["password"]).decode("utf-8")
        self._metadata = Metadata(namespace, name, secret.metadata.uid)
        self._username = username
        self._password = password
        self._validated = True

    def __str__(self):
        return f"{self.namespace}/{self.name.kubernetes_view} (uid: {self.uid})"

    def __repr__(self):
        return f"Secret({repr(self.namespace)}, {repr(self.name)}, {repr(self.uid)})"

    def __eq__(self, other):
        if not isinstance(other, Secret):
            return False
        return (
            self.metadata == other.metadata and
            self._username == other._username and
            self._password == other._password)

    def __hash__(self):
        return hash((self.metadata, self._username, self._password))

    @property
    @require_validated
    def helm_args(self) -> SubprocessArgs:
        return SubprocessArgs(["--username", self._username, "--password-stdin"], self._password)

    @property
    @require_validated
    def helmfile_keys(self):
        return {"username": self._username, "password": self._password}
