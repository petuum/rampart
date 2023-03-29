# Copyright 2023 Petuum, Inc. All Rights Reserved.

from base64 import b64decode
import copy
import hashlib
import json
import logging
import urllib.parse
import re

import kubernetes_asyncio as kubernetes

from .base_types import BaseElement, Metadata, KubernetesName
from .component_spec import ComponentSpec
from .secret import Secret

from ..constants import CONTROLLER_NAMESPACE, HELMFILE_TEMPLATE, LOGGING_FORMAT
from ..repository import get_global_repo_manager
from ..utils.classes import SubprocessArgs, ValidationError
from ..utils.deployment import require_validated
from ..utils.logger import GraphLogger

kubernetes.config.load_incluster_config()
core_api = kubernetes.client.CoreV1Api()

logging.basicConfig(format=LOGGING_FORMAT)
LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)


def _is_url(string):
    try:
        url = urllib.parse.urlparse(string)
        if url.netloc:
            return True
        else:
            return False
    except ValueError:
        return False


class ComponentChart(BaseElement):
    """
    This class manages the helm chart for a single component
    """
    def __init__(self, chart_name, chart_version, url, graph_metadata):
        self._url = url
        self._repo_name = self._generate_repo_name()
        self._repo = None
        metadata = Metadata(None, f"{self._repo_name}/{chart_name}",
                            f"{self._repo_name}/{chart_name}:{chart_version}")
        super().__init__(metadata)
        self._chart_name = chart_name
        self._chart_version = chart_version
        self._component_spec = None
        self._annotations = None
        self._graph_metadata = graph_metadata
        self._logger = GraphLogger(LOG, {"metadata": graph_metadata})

    # TODO: have a base class that supports getting a key from __init__ args
    # before creating the object
    @classmethod
    def generate_key(cls, chart_yaml):
        return hash(json.dumps(chart_yaml, sort_keys=True))

    @classmethod
    async def from_yaml(cls, yaml_obj, graph_metadata):
        chart_name = yaml_obj["name"]
        chart_version = yaml_obj.get("version", "latest")
        chart_repo = yaml_obj["repo"]
        chart_secret = yaml_obj.get("secret", {})
        if _is_url(chart_repo):
            return URLComponentChart(
                chart_name, chart_version, chart_repo,
                KubernetesName(chart_secret.get("name", "")), graph_metadata)
        else:
            return SecretComponentChart(
                chart_name, chart_version, KubernetesName(chart_repo), graph_metadata)

    async def validate(self):
        """
        Throws a `ValidationError` if this componentchart or any of its children are
        invalid. This call must be made before any function with the `@required_validated` decorator
        is called.
        """
        #  TODO: enable in validator pod
        if not self._url:
            raise ValidationError(
                {f"No repository URL found for chart {self._chart_name}:{self._chart_version}"})
        self._repo = await get_global_repo_manager().add_or_get_repo(
            self._repo_name, self._url, self.pull_args, self._graph_metadata)
        await self._repo.update_repo(self._graph_metadata)
        self._annotations = await self._repo.get_component_annotations(
                self._chart_name, self._chart_version, self._graph_metadata)

        self._component_spec = ComponentSpec(
            self._annotations, self._repo_name, self._chart_name, self._chart_version, self._url)

        await self._component_spec.validate()

        self._validated = True

    @property
    @require_validated
    def component_spec(self):
        return self._component_spec

    @property
    def pull_args(self) -> SubprocessArgs:
        return SubprocessArgs()

    @property
    def pull_keys(self):
        return {}

    @property
    @require_validated
    def repo(self):
        return self._repo

    @require_validated
    def to_deployment_yaml(self, name, namespace, values,
                           recreate_pods, deployment_kwargs=None, needs=None):
        """
        Fill out the requires yaml files needed for the `releases` section of the helmfile config.
        """
        yaml = copy.deepcopy(HELMFILE_TEMPLATE)
        yaml["values"] = [values]
        if deployment_kwargs:
            for key, value in deployment_kwargs.items():
                yaml[key] = value
        yaml["name"] = name
        yaml["namespace"] = namespace.kubernetes_view
        yaml["recreatePods"] = recreate_pods
        yaml["chart"] = self.name.original_view
        yaml["needs"] = needs or []
        if self._component_spec.version != "latest":
            yaml["version"] = self._component_spec.version
        else:
            yaml["version"] = ">0.0.0-0"

        yaml = {key: value for key, value in yaml.items() if value}

        return yaml

    @require_validated
    async def deploy(self):
        pass

    @require_validated
    async def teardown(self):
        pass

    def _generate_repo_name(self):
        """
        Generates the internal name of the repository for this chart.
        """
        url = self._url.strip("/")
        parts = urllib.parse.urlsplit(url)
        username, password = parts.username, parts.password
        if username is None and password is None:
            userinfo = ""
        elif password is None:
            userinfo = f"{username}@"
        elif username is None:
            # this should never happen
            raise ValidationError({"There is no such way to specify a `null` username in an url."
                                   "it means that there is a bug in `urllib.parse.urlsplit`."})
        else:
            userinfo = f"{username}:{password}@"
        # normalize hostname
        if parts.port:
            parts = parts._replace(netloc=f"{userinfo}{parts.hostname}:{parts.port}")
        else:
            parts = parts._replace(netloc=f"{userinfo}{parts.hostname}")
        # repo name does not need to be readable, one could always identify it by its url
        return hashlib.sha1(urllib.parse.urlunsplit(parts).strip("/").encode()).hexdigest()


class URLComponentChart(ComponentChart):
    """
    A component chart whos repo is specified by the RampartGraph CR as a URL
    """
    # TODO: add tests
    def __init__(self, chart_name, chart_version, url,
                 secret_name, graph_metadata):
        if secret_name:
            self._secret = Secret(graph_metadata.namespace, secret_name)
        else:
            self._secret = None
        super().__init__(chart_name, chart_version, url, graph_metadata)

    async def validate(self):
        if not _is_url(self._url):
            raise ValidationError({f"Chart repo {self._url} is not a valid URL"})
        if self._secret:
            await self._secret.validate()
        await super().validate()

    @property
    def pull_args(self) -> SubprocessArgs:
        if self._secret:
            return self._secret.helm_args
        return SubprocessArgs()

    @property
    def pull_keys(self):
        if self._secret:
            return self._secret.helmfile_keys
        return {}

    def _generate_repo_name(self):
        name = super()._generate_repo_name()
        if self._secret:
            return name + self._secret.name.rampart_view
        else:
            return name


class SecretComponentChart(ComponentChart):
    """
    A component chart whos repo is specified by the RampartGraph CR as a kubernetes secret.
    """
    # TODO: add tests
    def __init__(self, chart_name, chart_version, repo_name, graph_metadata):
        metadata = Metadata(None, f"{repo_name.kubernetes_view}/{chart_name}",
                            f"{repo_name.kubernetes_view}/{chart_name}:{chart_version}")
        BaseElement.__init__(self, metadata)
        self._repo_object_name = repo_name
        self._repo_object_namespace = graph_metadata.namespace
        self._data = {}
        self._url = None
        self._chart_name = chart_name
        self._chart_version = chart_version
        self._component_spec = None
        self._annotations = None
        self._graph_metadata = graph_metadata
        self._logger = GraphLogger(LOG, {"metadata": graph_metadata})

    async def validate(self):
        name = self._repo_object_name
        namespace = self._repo_object_namespace
        try:
            secret = await core_api.read_namespaced_secret(
                name.kubernetes_view, namespace.kubernetes_view)
        except kubernetes.client.rest.ApiException as exc:
            if exc.status == 404:
                try:
                    controller_namespace = KubernetesName(CONTROLLER_NAMESPACE)
                    secret = await core_api.read_namespaced_secret(
                        name.kubernetes_view, controller_namespace.kubernetes_view)
                except kubernetes.client.rest.ApiException as exc:
                    if exc.status == 404:
                        raise ValidationError({
                            f"Secret {name.kubernetes_view} not found in "
                            f"namespaces {namespace.kubernetes_view} or "
                            f"{controller_namespace.kubernetes_view}"})
                    else:
                        raise exc
            else:
                raise exc
        errors = []
        if "url" not in secret.data:
            errors.append(f'Key "url" not found in secret {namespace}/{name}')

        self._url = b64decode(secret.data["url"]).decode("utf-8")
        self._repo_name = self._generate_repo_name()
        self._repo = None
        self._data = {}

        # TODO: metadata shouldn't change from object creation. Find a way around this
        self._metadata = Metadata(None, f"{self._repo_name}/{self._chart_name}",
                                  f"{self._repo_name}/{self._chart_name}:{self._chart_version}")
        for key, value in secret.data.items():
            if key != "url":
                self._data[key] = b64decode(value).decode("utf-8").strip()

        await super().validate()

    @property
    def pull_args(self) -> SubprocessArgs:
        def dash(string):
            string = re.sub('(.)([A-Z][a-z]+)', r'\1-\2', string)
            return re.sub('([a-z0-9])([A-Z])', r'\1-\2', string).lower()

        pwd = ""
        args = []
        for key, value in self._data.items():
            key = dash(key)
            if key == "password" or key == "password-stdin":
                pwd = value

            if value is not True and value != "true":
                args += [f"--{key}", value]
            elif key != "force-update":
                args += [f"--{key}"]
        return SubprocessArgs(args, pwd)

    @property
    def pull_keys(self):
        def camel(string):
            substrings = string.split('-')
            if len(substrings) > 1:
                return substrings[0] + (''.join(substr.title() for substr in substrings[1:]))
            else:
                return string

        return {camel(key): value for key, value in self._data.items()
                if camel(key) != "forceUpdate"}

    def _generate_repo_name(self):
        name = super()._generate_repo_name()
        return name + "_full-secret_" + self._repo_object_name.rampart_view
