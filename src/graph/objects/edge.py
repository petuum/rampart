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

# TODO: split this file up into smaller files by edge/flow types
import aiofiles
import aiohttp
import asyncio
import base64
import enum
import logging
import os
import pathlib
import urllib.parse
import yaml

from abc import ABC, abstractmethod
from kubernetes_asyncio import client as k8s_client, config as k8s_config, watch as k8s_watch
from typing import List, Optional, Union

from .base_types import Metadata, KubernetesName
from ..k8s_templates import init_repo_job_template, pvc_template, owner_reference_template, \
    image_pull_secret_template
from ..utils.classes import GraphPhase, ValidationError, DeploymentError, collect_errors, Either
from ..utils.deployment import deploy_sub_namespace, require_validated, required_subprocess, \
    optional_deploy, patch_pv, optional_subprocess, optional_teardown
from ..utils.infra import pulsar_enabled
from ..utils.logger import GraphLogger
from ..utils.tree_utils import recursive_merge
from ..constants import FLOW_NAME_RE, HTTP_TIMEOUT, LOGGING_FORMAT, PULSAR_ADMIN_SERVICE, \
    PULSAR_CLIENT_SERVICE, PULSAR_DEPLOYMENT, RAMPART_CRD_API, RAMPART_CRD_KIND, \
    STORAGE_CLASS, PULSAR_TENANT, GENERATE_PULSAR_NAMESPACE, REPO_FLOW_INIT_TIMEOUT, \
    IMAGE_PULL_SECRET_PATH, UNICODE_PARAGRAPH_SEPARATOR_CLASS_CHARACTERS, RAMPART_REGISTRY, \
    RAMPART_FLOW_IMAGE, REPO_FLOW_SECRET_NAME, REPO_EDGE_SECRET_NAME, PULL_IMAGE_SECRET_NAME, \
    HNS_API, HNS_VERSION, HNS_KIND_PL
from ..utils.secret import create_secret_by_filepath


k8s_config.load_incluster_config()
custom_api = k8s_client.CustomObjectsApi()
core_api = k8s_client.CoreV1Api()
batch_api = k8s_client.BatchV1Api()

logging.basicConfig(format=LOGGING_FORMAT)
LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)


class FlowType(enum.Enum):
    VOLUME = enum.auto()
    PULSAR = enum.auto()
    REPOSITORY = enum.auto()


# Type of an edge is determined by the flow it connects to, so the type enum for edges is
# just an alias of FlowType.
EdgeType = FlowType


class IOPart(enum.Enum):
    INPUT = enum.auto()
    OUTPUT = enum.auto()


class BaseEdgeSpec(ABC):
    """
    Base class for edge specifications
    """
    def __init__(self, name: str, edge_type: EdgeType, part: IOPart,
                 remaining_specs: Optional[dict] = None):
        self._name = name
        self._part = part  # input or output
        self._edge_type = edge_type
        # TODO: Find a better way to handle type specific specs, like multiple inheritance
        # Different edge types have other spec fields only applicable to them
        # and they are passed in here.
        self._remaining_specs = remaining_specs or {}
        self._validated = False

    @property
    def type(self):
        return self._edge_type

    @property
    def part(self):
        """Input or output."""
        return self._part

    @property
    def name(self):
        return self._name

    @property
    def type_specific_specs(self):
        return self._remaining_specs

    @abstractmethod
    def matches(self, name):
        return

    async def validate(self):
        self._validated = True

    @property
    def validated(self):
        return self._validated


class SimpleEdgeSpec(BaseEdgeSpec):
    """
    Specification for an edge with a fixed name. If the component spec has a simple input edge
    with name "foo" and type "bar", the input edge "foo" for a component instance with that
    component spec must have type "bar"
    """
    def __init__(self, edge_type: EdgeType, name: str, part: IOPart, remaining_specs: dict = None):
        super().__init__(name, edge_type, part, remaining_specs)

    def matches(self, name):
        return name == self._name


class VariadicEdgeSpec(BaseEdgeSpec):
    """
    Specification for an edge using a prefix. If the component spec has a variadic input edge
    "foo*" with type "bar", any input edge that starts with "foo" for a component instance
    with that component spec must have type "bar".
    """
    def __init__(self, edge_type: EdgeType, prefix: str, part: IOPart,
                 remaining_specs: dict = None):
        super().__init__(prefix + "*", edge_type, part, remaining_specs)
        self._prefix = prefix

    @property
    def prefix(self):
        return self._prefix

    def matches(self, name):
        return name.startswith(self._prefix)

    async def validate(self):
        """
        Raises a `ValidationError` if the object is invalid. This call must be made
        before any function with the `@required_validated` decorator is called.

        Raises:
            ValidationError: If the mount path does not end with '*'
        """
        # TODO: remove type check here
        if (self.type is EdgeType.VOLUME) or (self.type is EdgeType.REPOSITORY):
            mount_path = self.type_specific_specs.get("mountPath", None)
            if mount_path and mount_path[-1] != "*":
                raise ValidationError({f"Default mount_path defined for {self.name} "
                                      f"must end with '*', but is {mount_path}"})
        self._validated = True


class Flow:
    """A Flow factory that produces proper flow objects based on `flow_type`.
    Whenever a subclass is declared, it is automatically registered and can be instantiated by
    calling `Flow.create(...)`.
    """
    _flow_cls_registry = {}

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__()
        if "flow_type" in kwargs:
            cls._flow_cls_registry[kwargs["flow_type"]] = cls

    @staticmethod
    def create(name: str, flow_type: FlowType, config: dict, graph_metadata: Metadata):
        try:
            flow_cls = Flow._flow_cls_registry[flow_type]
        except KeyError:
            raise ValueError(f"Unknown flow type: {flow_type.name}. "
                             f"This is a Rampart controller error; please report this bug.")
        return flow_cls(name, config, graph_metadata)


class BaseFlow(Flow, ABC):
    """
    Base class for flows
    """
    def __init__(self, name: Union[str, KubernetesName], config: dict, flow_type: FlowType,
                 uid: str, graph_metadata: Metadata):
        self._name = KubernetesName(name)
        self._type = flow_type
        self._uid = uid
        self._config = config
        self._validated = False
        self._graph_metadata = graph_metadata

    def __hash__(self):
        return hash(self._uid)

    def __eq__(self, other):
        if not isinstance(other, BaseFlow):
            return False
        return self._uid == other._uid

    @staticmethod
    async def batch_deploy(flows: List["BaseFlow"], workdir: str,
                           graph_metadata: Metadata) -> List[asyncio.Task]:
        """
        To be implemented by the inheriting subclasses:
        Deploy all the of the flows that match this flow subclass at once
        """
        return []

    @property
    def type(self):
        return self._type

    @property
    def name(self):
        return self._name

    @property
    def uid(self):
        return self._uid

    @property
    def config(self):
        return self._config

    async def validate(self):
        """
        Raises a `ValidationError` if the object is invalid. This call must be made
        before any function with the `@required_validated` decorator is called.

        Raises:
            ValidationError: If the flow has invalid characters in the name
        """
        if FLOW_NAME_RE.fullmatch(self._name.original_view):
            self._validated = True
        else:
            raise ValidationError({f"Invalid flow: {self._name.original_view}. "
                                   "Use alphanumeric, underscore, and dash only"})

    @property
    def validated(self):
        return self._validated


class PVFlow(BaseFlow, flow_type=FlowType.VOLUME):
    """
    Represents and handles the persistent volumes and persistent volume claims
    for connecting two components
    """

    def __init__(self, name: str, config: dict, graph_metadata: Metadata):
        metadata = graph_metadata
        name = KubernetesName(name)
        path = (f"{metadata.namespace.kubernetes_view}-"
                f"{metadata.name.kubernetes_view}-"
                f"{name.kubernetes_view}")
        super().__init__(name, config, FlowType.VOLUME, path, graph_metadata)

        self._path = path
        self._size = config["size"]
        self._reclaim_policy = config.get("reclaimPolicy", "Delete")
        self._namespace = None

    @property
    def path(self):
        return self._path

    @property
    def size(self):
        return self._size

    @property
    def reclaim_policy(self):
        return self._reclaim_policy

    @property
    def pvc_name(self):
        return self._path

    @property
    def namespace(self) -> Metadata:
        return self._namespace

    @namespace.setter
    def namespace(self, value: Metadata):
        self._namespace = value.copy()

    def to_pvc(self, namespace, storage_class):
        return pvc_template(self.pvc_name, namespace, storage_class, self.size)

    def customized_scalar(self, tag, value, style=None):
        should_use_block = False
        # Customized yaml style for converting commands in initContainers:
        # use block for multiline string
        # use default style for single line string
        for c in UNICODE_PARAGRAPH_SEPARATOR_CLASS_CHARACTERS:
            if c in value:
                should_use_block = True
                break

        if style is None:
            if should_use_block:
                style = '|'
            else:
                style = self.default_style

        node = yaml.representer.ScalarNode(tag, value, style=style)
        if self.alias_key is not None:
            self.represented_objects[self.alias_key] = node
        return node

    @staticmethod
    def _generate_namespace(graph_metadata: Metadata) -> str:
        # TODO: this will overlap with the namespace for a component named "rampart-flows"
        #       should probably alter this to not use the same format as component namespaces
        return (f"{graph_metadata.namespace.kubernetes_view}-"
                f"{graph_metadata.name.kubernetes_view}-"
                f"rampart-flows-{FlowType.VOLUME.name.lower()}")

    @staticmethod
    def _generate_release(graph_metadata: Metadata) -> str:
        return (f"flows-{FlowType.VOLUME.name.lower()}")

    @classmethod
    async def batch_teardown(cls, graph_metadata: Metadata):
        """Performs a teardown of all volume flows for a given graph"""
        subnamespace = cls._generate_namespace(graph_metadata)
        parent_namespace = graph_metadata.namespace
        await optional_subprocess(
            graph_metadata, False, None,
            "helm", "uninstall", "-n", subnamespace, "flows-volume", "--wait")
        await optional_teardown(
            custom_api.delete_namespaced_custom_object,
            lambda e: type(e) == k8s_client.rest.ApiException,
            HNS_API, HNS_VERSION, parent_namespace.kubernetes_view, HNS_KIND_PL,
            subnamespace)

    @classmethod
    async def batch_deploy(cls, flows: List["PVFlow"], workdir: str,
                           graph_metadata: Metadata, extra_values={}) -> List[asyncio.Task]:
        """
        Deploy all the of the volume flows for a given graph. Returns a list of tasks
        that the caller will need to manage to finish deploying the flows.
        """
        # Deployment of "flows" is used to manage pv reclaim policies in order
        # to clear up underlying pv paths according to flows' reclaim policies.
        # see `deployment_util.patch_pv` to learn how pv's are patched.
        # 1. "Delete" flow -> "Delete" pv -> path deleted when pv is deleted
        # 2. "Retain" flow -> "Retain" pv -> path not deleted when pv is deleted
        metadata = graph_metadata
        logger = GraphLogger(LOG, {"metadata": metadata})
        _flow_ns_metadata = Metadata(metadata.namespace,
                                     cls._generate_namespace(graph_metadata),
                                     None)
        # deploy flow namespace
        owner_reference = owner_reference_template(metadata.name, metadata.uid, RAMPART_CRD_KIND,
                                                   RAMPART_CRD_API)
        tasks = [deploy_sub_namespace(_flow_ns_metadata.name,
                                      _flow_ns_metadata.namespace,
                                      owner_reference, custom_api, core_api, metadata)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        collect_errors(results)
        _flow_ns_metadata = results[0]
        for flow in flows:
            flow.namespace = _flow_ns_metadata
        # generate helmfile release for flows
        chart_name = f"{metadata.name}_flows_helm"
        flow_chart_dir = os.path.join(workdir, chart_name)
        base_chart_dir = os.path.join(pathlib.Path(__file__).parent.parent.absolute(),
                                      "base_flow_chart")
        helm_init_args = ["helm", "create", flow_chart_dir, "-p", base_chart_dir]
        await required_subprocess(metadata, True, None, *helm_init_args)
        chart_values = {"pvc_list": [flow.to_pvc(_flow_ns_metadata.name, STORAGE_CLASS)
                                     for flow in flows],
                        "flow_image": RAMPART_FLOW_IMAGE,
                        "pull_image_secret_name": PULL_IMAGE_SECRET_NAME}
        if extra_values:
            recursive_merge(extra_values, chart_values)

        if IMAGE_PULL_SECRET_PATH:
            logger.info(
                f"creating secret {PULL_IMAGE_SECRET_NAME} from filepath "
                f"in the namespace:{_flow_ns_metadata.name.kubernetes_view}",
                extra={"phase": GraphPhase.DEPLOYMENT})
            await create_secret_by_filepath(PULL_IMAGE_SECRET_NAME,
                                            _flow_ns_metadata.name.kubernetes_view,
                                            IMAGE_PULL_SECRET_PATH)

        values_file = os.path.join(workdir, f"{metadata.name}-flows.yaml")
        yaml.representer.BaseRepresenter.represent_scalar = cls.customized_scalar
        async with aiofiles.open(values_file, "w") as f:
            await f.write(yaml.dump(chart_values))
        flow_release = {
            "name": cls._generate_release(graph_metadata),
            "namespace": _flow_ns_metadata.name.kubernetes_view,
            "chart": chart_name,
            "version": "0.0.0",
            "values": [values_file]
        }
        flow_helmfile = {"repositories": [], "releases": [flow_release]}
        filename = os.path.join(workdir, f"flows-{metadata.name}_helmfile.yaml")
        async with aiofiles.open(filename, "w") as yaml_file:
            await yaml_file.write(yaml.dump(flow_helmfile))
        deploy_args = ["helmfile", "--file", filename, "apply"]

        async def clean_up_callback():
            # TODO: run helm rollback with timeout before falling back to uninstall
            logger.info(f"deployment cancelled, cleaning up flow {flow_release['name']} "
                        f"in namespace {flow_release['namespace']}",
                        extra={"phase": GraphPhase.TEARDOWN})
            await optional_subprocess(metadata, False, None, "helm", "uninstall", "-n",
                                      flow_release["namespace"], flow_release["name"], "--wait")

        await required_subprocess(metadata, True, clean_up_callback, *deploy_args)
        # patching the pv, see deployment_util.patch_pv for detail
        pvc_names = {flow.pvc_name for flow in flows}
        pvc_to_flow = {flow.pvc_name: flow for flow in flows}
        # TODO: pv clean-ups may need to be handled by some deletion webhook. Using ownerreference
        #   is simple but has limitations like a owner cannot be cross-namespaced. This is the
        #   reason why a pv's ownerreference is set to a namespace causing a delayed clean-up, i.e.,
        #   pv's are deleted only when the entire graph or a component is deleted.
        owner_reference = owner_reference_template(_flow_ns_metadata.name, _flow_ns_metadata.uid,
                                                   "namespace", "v1")
        patch_tasks = [asyncio.create_task(patch_pv(_flow_ns_metadata.name,
                                                    pvc_names, core_api,
                                                    owner_reference, pvc_to_flow))]
        return patch_tasks


class PulsarFlow(BaseFlow, flow_type=FlowType.PULSAR):
    """
    Represents and handles the pulsar state for connecting two components
    """

    def __init__(self, name: str, config: dict, graph_metadata: Metadata):
        pulsar_namespace = GENERATE_PULSAR_NAMESPACE(graph_metadata)
        name = KubernetesName(name)
        super().__init__(name, config, FlowType.PULSAR,
                         f"{pulsar_namespace}-{name.kubernetes_view}",
                         graph_metadata)
        self._topic = f"{pulsar_namespace}/{name.original_view}"

    async def validate(self):
        """
        Raises a `ValidationError` if the object is invalid. This call must be made
        before any function with the `@required_validated` decorator is called.

        Raises:
            ValidationError: If no deployed graph provides pulsar
        """
        if not pulsar_enabled():
            raise ValidationError({"Pulsar service inaccessible. "
                                   "Ensure pulsar dependency is installed."})
        await super().validate()

    @property
    def topic(self):
        return self._topic

    @staticmethod
    async def batch_deploy(flows: List["PulsarFlow"], workdir: str,
                           graph_metadata: Metadata) -> List[asyncio.Task]:
        """
        Deploy all the of the pulsar flows for a given graph. Returns an empty list of tasks
        to match the type of other versions of `batch_deploy`.

        The actual implementation here is just creating the appropriate pulsar tenants
        and namespaces that the components can use.
        """
        if not pulsar_enabled():
            return []
        try:
            async with aiohttp.ClientSession(timeout=HTTP_TIMEOUT) as session:
                async with session.put(
                        f"http://{PULSAR_ADMIN_SERVICE}/admin/v2/tenants/{PULSAR_TENANT}",
                        json={"allowedClusters": [PULSAR_DEPLOYMENT]}) as resp:
                    # We need to succeed in case of a 409 result in order for redeployment to work
                    if not (resp.status == 409 or resp.status < 300):
                        text = await resp.text()
                        raise DeploymentError(
                            {f"Cannot create Pulsar tenant: [{resp.status}] {text}"})

                async with session.put(
                        f"http://{PULSAR_ADMIN_SERVICE}/admin/v2/namespaces/"
                        f"{GENERATE_PULSAR_NAMESPACE(graph_metadata)}",
                        skip_auto_headers=["Content-Type"]) as resp:
                    # We need to succeed in case of a 409 result in order for redeployment to work
                    if not (resp.status == 409 or resp.status < 300):
                        text = await resp.text()
                        raise DeploymentError(
                            {f"Cannot create Pulsar namespace: [{resp.status}] {text}"})
        except (aiohttp.ClientConnectionError, asyncio.TimeoutError):
            raise DeploymentError({"Pulsar is enabled but its service is not available yet."})

        for flow in flows:
            # Optional deployment here is required for redeployment
            await optional_deploy(flow.deploy)
        return []

    @require_validated
    async def deploy(self):
        """Deploy a pulsar topic for this flow"""
        # The callee must make this deployment not fail in case the topic
        # already exists
        async with aiohttp.ClientSession(timeout=HTTP_TIMEOUT) as session:
            async with session.put(f"http://{PULSAR_ADMIN_SERVICE}/"
                                   f"admin/v2/persistent/{self.topic}",
                                   skip_auto_headers=["Content-Type"]) as resp:
                status = resp.status
                if not (status < 300 or status == 409):
                    raise DeploymentError({f"Status code: {status} when creating pulsar topic "
                                           f"{self._topic}"})

    @require_validated
    async def teardown(self, graph_uid, pulsar_namespace):
        pass


class RepositoryFlow(PVFlow, flow_type=FlowType.REPOSITORY):
    """
    Implements an extension of a PVFlow that also sets up a git or DVC (https://dvc.org) repo
    for the mounted volumes
    """
    class RepoKind(enum.Enum):
        GIT = enum.auto()
        DVC = enum.auto()

    def __init__(self, name: str, config: dict, graph_metadata: Metadata):
        super().__init__(name, config, graph_metadata)
        self._type = FlowType.REPOSITORY
        self._repo_kind = self.RepoKind[config["kind"].upper()]
        self._repo_origin_mount_path = os.path.join("/.rampart/repo_origin", self.path)
        self._repo_secret_mount_path = os.path.join("/.rampart/repo_secret", self.path)

    @property
    def repo_kind(self):
        return self._repo_kind

    async def validate(self):
        """
        Raises a `ValidationError` if the object is invalid. This call must be made
        before any function with the `@required_validated` decorator is called.

        Raises:
            ValidationError: If the flow is invalid
        """
        errors = []
        try:
            await super().validate()
        except ValidationError as err:
            errors = err.errors
        if self.repo_kind is self.RepoKind.DVC:
            remote = self.config.get("remote")
            storage_remote = self.config.get("storageRemote")
            storage_secret = self.config.get("storageSecret")
            storage_secret_type = self.config.get("storageSecretType")
            if (remote and not storage_remote and storage_secret and not storage_secret_type):
                errors.append("storageSecretType is required when storageRemote is not provided.")
            if storage_remote and urllib.parse.urlsplit(storage_remote).scheme != "s3":
                errors.append(f"DVC remote: {storage_remote} is not supported.")
            elif storage_secret_type and storage_secret_type != "s3":
                errors.append(f"DVC remote type: {storage_secret_type} is not supported.")
        if errors:
            self._validated = False
            raise ValidationError(errors)
        self._validated = True

    def need_pv(self):
        conf = self._config
        is_git = self.repo_kind is self.RepoKind.GIT
        is_dvc = self.repo_kind is self.RepoKind.DVC
        remote = conf.get("remote")
        storage_remote = conf.get("storageRemote")
        storage_secret = conf.get("storageSecret")

        git_need_pv = is_git and (remote is None)
        dvc_need_pv = is_dvc and (remote is None or
                                  (storage_secret is not None and storage_remote is None))

        return git_need_pv or dvc_need_pv

    def flows_need_init(self):
        conf = self._config
        is_git = self.repo_kind is self.RepoKind.GIT
        is_dvc = self.repo_kind is self.RepoKind.DVC

        if is_git and self.need_pv():
            return False

        has_remote = conf.get("remote") is not None

        return (is_git or is_dvc) and has_remote

    @require_validated
    async def init_flow_content(self, image_pull_secret_name=None):
        """Instantiates all of the repository file structure"""
        # Cases based on the two kinds of repo flows supprted (git and dvc):
        # Case 1: init none
        init_git, init_artifact, init_dvc, link_storage = False, False, False, False
        # Case 2: init git only
        if self.repo_kind is self.RepoKind.GIT and not self.config.get("remote"):
            init_git = True
        # Case 3: init git and dvc
        elif (self.repo_kind is self.RepoKind.DVC and not self.config.get("remote")
                and self.config.get("storageRemote")):
            init_git, init_dvc, link_storage = True, True, True
        # Case 4: init storage
        elif (self.repo_kind is self.RepoKind.DVC and self.config.get("remote")
                and not self.config.get("storageRemote")):
            # This git remote is not controlled by rampart. It is not clear whether we should
            # push to it with dvc's remote changes. So for now, we only create a storage
            # folder and let component make the change locally.
            init_artifact = True
        # Case 5 init git, dvc and storage, also links the storage
        elif (self.repo_kind is self.RepoKind.DVC and not self.config.get("remote")
                and not self.config.get("storageRemote")):
            init_git, init_artifact, init_dvc, link_storage = True, True, True, True

        if any((init_git, init_artifact, link_storage, init_dvc)):
            pull_secrets = [{"name": image_pull_secret_name}] if image_pull_secret_name else None
            job = init_repo_job_template(self.pvc_name, self.config, self._repo_origin_mount_path,
                                         init_git, init_artifact, init_dvc, link_storage,
                                         pull_secrets)
            # TODO: use `ttl_seconds_after_finished` to garbage collect the job
            job = await batch_api.create_namespaced_job(
                body=job, namespace=self.namespace.name.kubernetes_view)
            async with k8s_watch.Watch() as watch:
                async for event in watch.stream(
                        batch_api.list_namespaced_job, self.namespace.name.kubernetes_view,
                        field_selector=f"metadata.name={job.metadata.name}",
                        timeout_seconds=REPO_FLOW_INIT_TIMEOUT):
                    conditions = event["object"].status.conditions or []
                    if (event["object"].status.succeeded == 1
                            or any(c.type == "Complete" for c in conditions)):
                        return
                    if (event["object"].status.failed == 1
                            or any(c.type == "Failed" for c in conditions)):
                        raise DeploymentError(
                            {f"Failed to initialize repo for flow {self.name}."})
                    if event["type"].lower() == "deleted":
                        raise DeploymentError({"Repo init job deleted unexpectedly."})
            raise DeploymentError({f"Timeout initializing repo for flow {self.name}."})

    @staticmethod
    def _generate_namespace(graph_metadata: Metadata) -> str:
        return (f"{graph_metadata.namespace.kubernetes_view}-"
                f"{graph_metadata.name.kubernetes_view}-"
                f"rampart-flows-{FlowType.REPOSITORY.name.lower()}")

    @staticmethod
    def _generate_release(graph_metadata: Metadata) -> str:
        return (f"flows-{FlowType.REPOSITORY.name.lower()}")

    @classmethod
    async def batch_teardown(cls, graph_metadata: Metadata):
        """Tears down all of the deployed infrastructure for the repository flows of a graph"""
        subnamespace = cls._generate_namespace(graph_metadata)
        parent_namespace = graph_metadata.namespace
        await optional_subprocess(
            graph_metadata, False, None,
            "helm", "uninstall", "-n", subnamespace, "flows-repository", "--wait")
        await optional_teardown(
            custom_api.delete_namespaced_custom_object,
            lambda e: type(e) == k8s_client.rest.ApiException,
            HNS_API, HNS_VERSION, parent_namespace.kubernetes_view, HNS_KIND_PL,
            subnamespace)

    @classmethod
    async def batch_deploy(cls, flows: List["RepositoryFlow"], workdir: str,
                           graph_metadata: Metadata) -> List[asyncio.Task]:
        """
        Deploy all the of the repo flows for a given graph. Returns a list of tasks
        that the caller will need to manage to finish deploying the flows.
        """
        flows_need_pv = [flow for flow in flows if flow.need_pv()]
        flows_need_init = [flow for flow in flows if flow.flows_need_init()]
        if not flows_need_init and not flows_need_pv:
            return []
        init_containers = []
        secret_volume_list = []
        for flow in flows_need_init:
            # TODO: deduplication with create_pod_preset_values() in RepositoryEdge
            default_username = "" if flow.config.get("remote", "") else "Rampart"
            default_email = "" if flow.config.get("remote", "") else "rampart@petuum.com"
            with pathlib.Path(__file__).parent.parent.joinpath("k8s_templates",
                                                               "clone_repo.sh").open("rt") as f:
                command = ["sh", "-c", f.read()]

            env = [
                {"name": "REPO", "value": flow.config.get("remote", "")},
                {"name": "BRANCH", "value": flow.config.get("defaultBranch")},
                {"name": "DIR", "value": flow._repo_origin_mount_path},
                {"name": "USER_NAME", "value": flow.config.get("username", default_username)},
                {"name": "USER_EMAIL", "value": flow.config.get("useremail", default_email)},
            ]
            secret = flow.config.get("secret", "")
            remote = flow.config.get("remote", "")
            mount_volumes = [{"name": flow.pvc_name, "mountPath": flow._repo_origin_mount_path}]

            url = urllib.parse.urlsplit(remote)
            if url.scheme in ["http", "https", ""]:
                secret_volume_list.append({
                    "name": f"git-secret-{flow.name.kubernetes_view}",
                    "secret": {"secretName": secret, "defaultMode": 256}
                })
                mount_path = os.path.join(flow._repo_secret_mount_path, "git")
                mount_volumes.append({"name": secret_volume_list[-1]["name"],
                                      "mountPath": mount_path})
                if url.scheme == "":
                    key_path = f"{os.path.join(mount_path, 'ssh-privatekey')}"
                    env.append({"name": "SSH_PRIVATE_KEY", "value": key_path})
                elif url.scheme in ["http", "https"]:
                    username_file = os.path.join(mount_path, "username")
                    password_file = os.path.join(mount_path, "password")
                    env += [{"name": "CRED_USERNAME", "value": username_file},
                            {"name": "CRED_PASSWORD", "value": password_file}]

            init_containers.append({
                "name": f"git-clone-{flow.name.kubernetes_view}",
                "image": f"{RAMPART_REGISTRY}/dev/dvc:2.9.3",
                "command": command,
                "mount_volumes": mount_volumes,
                "env": env
            })

        extra_values = {}
        if flows_need_init:
            extra_values['empty_dir_list'] = [{'name': flow.pvc_name} for flow in flows_need_init]
        if init_containers:
            extra_values['init_containers'] = init_containers
        if secret_volume_list:
            extra_values['secret_volume_list'] = secret_volume_list

        remaining_tasks = await super(RepositoryFlow, RepositoryFlow).batch_deploy(flows_need_pv,
                                                                                   workdir,
                                                                                   graph_metadata,
                                                                                   extra_values)

        if not flows_need_pv:
            return []
        secret_name = None
        if IMAGE_PULL_SECRET_PATH:
            secret_name = REPO_FLOW_SECRET_NAME
            await create_secret_by_filepath(secret_name,
                                            flows_need_pv[0].namespace.name.kubernetes_view,
                                            IMAGE_PULL_SECRET_PATH)
        init_tasks = [flow.init_flow_content(secret_name) for flow in flows_need_pv]
        collect_errors(await asyncio.gather(*init_tasks, return_exceptions=True))
        return remaining_tasks


class Edge:
    """An Edge factory that produces proper edge objects based on `edge_type`.
    Whenever a subclass is declared, it is automatically registered and can be instantiated by
    calling `Edge.create(...)`.
    """
    _edge_cls_registry = {}

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__()
        if "edge_type" in kwargs:
            cls._edge_cls_registry[kwargs["edge_type"]] = cls

    @staticmethod
    def create(name: str, edge_type: EdgeType, part: IOPart, config: dict,
               flow: Union[Either.Success, Either.Failure],
               graph_metadata: Metadata, component_metadata: Metadata):
        try:
            edge_cls = Edge._edge_cls_registry[edge_type]
        except KeyError:
            raise ValueError(f"Unknown edge type: {edge_type}. "
                             f"This is a Rampart controller error; please report this bug.")
        return edge_cls(name, part, config, flow, graph_metadata, component_metadata)


class BaseEdge(Edge, ABC):
    """
    Base class of all edge classes.
    Important note: all edges with a mount path should have a `mount_path` attribute/property,
    whose value is the path string.
    """

    def __init__(self, name: Union[str, KubernetesName], part: IOPart, config: dict,
                 flow: Union[Either.Success, Either.Failure],
                 edge_type: EdgeType, graph_metadata: Metadata, component_metadata: Metadata):
        self._name = KubernetesName(name)
        self._part = part
        self._flow = flow
        self._type = edge_type
        self._config = config
        self._graph_metadata = graph_metadata
        self._component_metadata = component_metadata
        self._validated = False

    @property
    def name(self):
        return self._name

    @property
    def part(self):
        """Input or output."""
        return self._part

    @property
    def validated(self):
        return self._validated

    async def validate(self, spec: BaseEdgeSpec):
        """
        Raises a `ValidationError` if the object is invalid. This call must be made
        before any function with the `@required_validated` decorator is called.

        Raises:
            ValidationError: If the edge is invalid
        """
        # By default, check whether config type is same as spec type.
        errors = []
        if isinstance(spec, SimpleEdgeSpec):
            if spec.type is not self.type:
                errors.append(f"{spec.part.name.capitalize()} {self.name} with type "
                              f"{self.type.name} does not match ComponentSpec "
                              f"{spec.part.name.lower()} {spec.name} with type {spec.type.name}")
        elif isinstance(spec, VariadicEdgeSpec):
            if spec.type is not self.type:
                errors.append(f"{spec.part.name.capitalize()} {self.name} with type "
                              f"{self.type.name} does not match variadic ComponentSpec "
                              f"{spec.part.name.lower()} "
                              f"{self.name} with prefix {spec.prefix} and type {spec.type.name}")
        # Delegate extra validations to child classes and collect the ValidationError's.
        errors.extend(self._validate(spec))
        if errors:
            raise ValidationError(errors)
        self._validated = True

    def _validate(self, spec: BaseEdgeSpec) -> List[ValidationError]:
        """Validate self and return validation errors.
        To be implemented by child classes.
        """
        return []

    @property
    def flow_name(self):
        if self._flow:
            return self._flow.value.name
        else:
            return self._flow.error_value

    @property
    def flow(self):
        if self._flow:
            return self._flow.value
        else:
            return None

    @property
    def type(self):
        return self._type

    @property
    @require_validated
    def resource(self):
        """
        The primary way the component will interact with the flow. Contains some
        flow-type specific string that will allow the component to connect (e.g. mount path)
        """
        return ""

    @property
    def component_metadata(self) -> Metadata:
        return self._component_metadata

    @require_validated
    def create_k8s_object_yamls(self, namespace: Metadata, seen_flows: set):
        return []

    @require_validated
    def create_pod_preset_values(self, seen_flows: set):
        """
        Creates a template for values that should be attached to all pods in a
        component namespace.

        Here we attach an environment variable so that the pod knows that this
        edge exists and has some resource string (see the `resource` function).
        """
        env_var = {"name": f"RAMPART_{self.part.name}_{self.name.rampart_view}",
                   "value": self.resource}
        return {
            "spec": {
                "containerTemplate": {
                    "env": [env_var],
                },
                "podTemplate": {}
            }
        }

    @require_validated
    def post_deploy_hooks(self, namespace: Metadata, seen_flows: set):
        """Coroutines to be executed right after edge deployments"""
        return []


class VolumeEdge(BaseEdge, edge_type=EdgeType.VOLUME):
    """
    This class represents and manages attaching a PV/volume flow to a component
    """
    def __init__(self, name: str, part: IOPart, config: dict,
                 flow: Union[Either.Success, Either.Failure],
                 graph_metadata: Metadata, component_metadata: Metadata):
        super().__init__(name, part, config, flow, EdgeType.VOLUME,
                         graph_metadata, component_metadata)

        mount_path = self._config.get("mountPath", None)

        if mount_path:
            self._mount_path = "/" + mount_path.strip("/ ")
        else:
            self._mount_path = None

    @property
    def mount_path(self):
        """
        This value is redundant with resource, because
        there are some times when we want to make clear that
        we are dealing with the mount path as a path per se,
        rather than a some string passed to the user
        """
        return self._mount_path

    def _validate(self, spec: BaseEdgeSpec = None):
        errors = []
        if isinstance(spec, SimpleEdgeSpec):
            self._mount_path = self._mount_path \
                or spec.type_specific_specs.get("mountPath", None) \
                or f"/{self.name}"
        elif isinstance(spec, VariadicEdgeSpec):
            if not self._mount_path:
                spec_default = spec.type_specific_specs.get("mountPath", None)
                if spec_default:
                    suffix = self.name.rampart_view[len(spec.prefix):]
                    # Assuming that `spec_default[-1] == '*'`. If it isn't true,
                    # it should already be caught by spec validation earlier.
                    self._mount_path = f"{spec_default[:-1]}{suffix}"
                else:
                    self._mount_path = f"/{self.name}"
        else:  # this config does not have a spec defined
            if not self._mount_path:
                self._mount_path = f"/{self.name}"
        return errors

    @property
    @require_validated
    def resource(self):
        """
        The component can use the attached volume flow by using the directory with
        the returned path.
        """
        return self._mount_path

    @require_validated
    def create_k8s_object_yamls(self, namespace: Metadata, seen_flows: set):
        """
        Create configs so we can deploy the appropriate PVC's for this edge's namespace
        """
        if self.flow not in seen_flows:
            return [self.flow.to_pvc(namespace.name, STORAGE_CLASS)]
        return []

    @require_validated
    def create_pod_preset_values(self, seen_flows: set):
        """
        Creates a template for values that should be attached to all pods in a
        component namespace.

        In addition to the default resource environment variable, we attach a PVC
        and a volume mount.
        """
        preset = super().create_pod_preset_values(seen_flows)
        mount = {
            "name": f"flow-volume-{self.flow_name.kubernetes_view}",
            "mountPath": self.mount_path,
            "readOnly": True if self.part is IOPart.INPUT else False
        }
        volumes = [{
            "name": mount["name"],
            "persistentVolumeClaim": {
                "claimName": self.flow.pvc_name
            }
        }] if self.flow not in seen_flows else []
        preset["spec"]["containerTemplate"]["volumeMounts"] = [mount]
        preset["spec"]["podTemplate"]["volumes"] = volumes
        return preset

    @require_validated
    def post_deploy_hooks(self, namespace: Metadata, seen_flows: set):
        """
        After the PVC's are deployed, we need to patch the parent PV's so that they are destroyed
        when the component is removed.
        """
        if self.flow not in seen_flows:
            pvc = self.flow.to_pvc(namespace.name, STORAGE_CLASS)
            owner_reference = owner_reference_template(namespace.name, namespace.uid,
                                                       "namespace", "v1")
            return [patch_pv(namespace.name, [pvc["metadata"]["name"]], core_api, owner_reference)]
        return []


class PulsarEdge(BaseEdge, edge_type=EdgeType.PULSAR):
    """
    This class represents and manages attaching a pulsar flow to a component
    """
    def __init__(self, name: str, part: IOPart, config: dict,
                 flow: Union[Either.Success, Either.Failure],
                 graph_metadata: Metadata, component_metadata: Metadata):
        super().__init__(name, part, config, flow, EdgeType.PULSAR,
                         graph_metadata, component_metadata)

    @property
    @require_validated
    def resource(self):
        """
        The component can use the pulsar flow by connecting to the returned pulsar topic.
        """
        return f"pulsar://{PULSAR_CLIENT_SERVICE}/{self.flow.topic}"


class RepositoryEdge(VolumeEdge, edge_type=EdgeType.REPOSITORY):
    """
    This class represents and manages attaching a repository flow to a component
    """
    def __init__(self, name: str, part: IOPart, config: dict,
                 flow: Union[Either.Success, Either.Failure],
                 graph_metadata: Metadata, component_metadata: Metadata):
        super().__init__(name, part, config, flow, graph_metadata, component_metadata)
        self._type = EdgeType.REPOSITORY
        self._image_pull_secret_name = REPO_EDGE_SECRET_NAME
        self._repo_origin_mount_path = (f"{self.flow._repo_origin_mount_path}"
                                        f"-{self.part.name.lower()}"
                                        f"-{self.name.kubernetes_view}")
        self._repo_secret_mount_path = (f"{self.flow._repo_secret_mount_path}"
                                        f"-{self.part.name.lower()}"
                                        f"-{self.name.kubernetes_view}")

    @require_validated
    def create_pod_preset_values(self, seen_flows: set):
        """
        Creates a template for values that should be attached to all pods in a
        component namespace.

        In addition to the default resource environment variable and volume
        presets, we attach an init container that sets up the respository.
        """
        if self.flow.need_pv():
            preset = super().create_pod_preset_values(seen_flows)
        else:
            # don't need the volumes and mounts created by VolumeEdge
            preset = super(VolumeEdge, self).create_pod_preset_values(seen_flows)
        volume_mounts = [
            {
                "name": f"flow-volume-clone-{self.part.name.lower()}-{self.name.kubernetes_view}",
                "mountPath": self.mount_path,
                "readOnly": False
            }
        ]
        if not self._edge_secret_created(seen_flows) and IMAGE_PULL_SECRET_PATH:
            preset["spec"]["podTemplate"]["imagePullSecrets"] = \
                [{"name": self._image_pull_secret_name}]
        # basic init container preset
        local_repo = os.path.join(self._repo_origin_mount_path, "bare.git")
        default_username = "" if self.flow.config.get("remote", "") else "Rampart"
        default_email = "" if self.flow.config.get("remote", "") else "rampart@petuum.com"
        with pathlib.Path(__file__).parent.parent.joinpath("k8s_templates",
                                                           "clone_repo.sh").open("rt") as f:
            command = ["sh", "-c", f.read()]
        # TODO: consider reducing the number of init containers to one, instead of one for each edge
        init_containers = [{
            "name": (f"git-clone-{self.part.name.lower()}-"
                     f"{self.name.kubernetes_view}"),
            "image": f"{RAMPART_REGISTRY}/dev/dvc:2.9.3",
            "command": command,
            "env": [
                {"name": "REPO", "value": self.flow.config.get("remote", local_repo)},
                {"name": "BRANCH", "value": self.flow.config.get("defaultBranch")},
                {"name": "DIR", "value": self.mount_path},
                {"name": "USER_NAME", "value": self.flow.config.get("username", default_username)},
                {"name": "USER_EMAIL", "value": self.flow.config.get("useremail", default_email)},
            ]
        }]
        # extra presets shared by all containers
        volumes = [{
            "name": volume_mounts[0]["name"],
            "emptyDir": {}
        }]
        secret = self.flow.config.get("secret", "")
        remote = self.flow.config.get("remote", "")
        if remote and secret:
            env = init_containers[0]["env"]
            url = urllib.parse.urlsplit(remote)
            if url.scheme in ["http", "https", ""]:
                volumes.append({
                    "name": f"git-secret-{self.flow_name.kubernetes_view}",
                    "secret": {"secretName": secret, "defaultMode": 256}
                })
                mount_path = os.path.join(self._repo_secret_mount_path, "git")
                volume_mounts.append({"name": volumes[-1]["name"], "mountPath": mount_path})
            if url.scheme == "":
                key_path = f"{os.path.join(mount_path, 'ssh-privatekey')}"
                env.append({"name": "SSH_PRIVATE_KEY", "value": key_path})
            elif url.scheme in ["http", "https"]:
                username_file = os.path.join(mount_path, "username")
                password_file = os.path.join(mount_path, "password")
                env += [{"name": "CRED_USERNAME", "value": username_file},
                        {"name": "CRED_PASSWORD", "value": password_file}]
            # else we don't know the expected secret type, do nothing.
        storageSecret = self.flow.config.get("storageSecret", "")
        storageRemote = self.flow.config.get("storageRemote", "")
        if self.flow.repo_kind is self.flow.RepoKind.DVC:
            env = init_containers[0]["env"]
            # "extra remote" makes sure that this dvc repo has at least one working remote
            # intrudoced mainly for the following cases:
            # 1. using external git repo but a local storage
            # 2. using external git repo but it does not have a default remote pre configured
            if remote and not storageRemote and not storageSecret:
                # pick up the storage folder previously created by flow
                env += [
                    {"name": "EXTRA_REMOTE_NAME",
                     "value": self.flow.config.get("storageRemoteName", "rampart-local")},
                    {"name": "EXTRA_REMOTE",
                     "value": os.path.join(self._repo_origin_mount_path, "artifact")}]
            elif remote and storageRemote:
                # storage remote already configured in the external git repo will be overridden
                # in case of name conflict
                env += [
                    {"name": "EXTRA_REMOTE_NAME",
                     "value": self.flow.config.get("storageRemoteName", "rampart-external")},
                    {"name": "EXTRA_REMOTE",
                     "value": storageRemote}]
            if remote and storageSecret:
                # attempts to set secret for `config["storageRemoteName"]` or the default storage.
                # if non of them exists, we still have "rampart-external"
                env += [{"name": "STORAGE_REMOTE_NAME",
                         "value": self.flow.config.get("storageRemoteName")}]
                volumes.append({
                    "name": f"dvc-secret-{self.flow_name.kubernetes_view}",
                    "secret": {"secretName": storageSecret, "defaultMode": 256}
                })
                mount_path = os.path.join(self._repo_secret_mount_path, "dvc")
                volume_mounts.append({"name": volumes[-1]["name"], "mountPath": mount_path})
                # TODO: support more storage types
                asccess_key_id = os.path.join(mount_path, "access_key_id")
                secret_access_key = os.path.join(mount_path, "secret_access_key")
                env += [{"name": "ACCESS_KEY_ID", "value": asccess_key_id},
                        {"name": "SECRET_ACCESS_KEY", "value": secret_access_key}]
        if preset["spec"]["containerTemplate"].get("volumeMounts"):
            preset["spec"]["containerTemplate"]["volumeMounts"][0]["mountPath"] \
                = self._repo_origin_mount_path
        init_containers[0]["volumeMounts"] \
            = preset["spec"]["containerTemplate"].get("volumeMounts", []) + volume_mounts
        preset["spec"]["podTemplate"]["initContainers"] = init_containers
        preset["spec"]["podTemplate"]["volumes"] = preset["spec"]["podTemplate"].get("volumes", [])\
            + volumes
        preset["spec"]["containerTemplate"]["volumeMounts"] = \
            preset["spec"]["containerTemplate"].get("volumeMounts", []) + volume_mounts

        preset["spec"]["containerTemplate"]["env"] = (
            preset["spec"]["containerTemplate"].get("env", []) +
            [{"name": f"RAMPART_REPO_TYPE_{self.part.name}_{self.name.rampart_view}",
              "value": self.flow.repo_kind.name}])
        return preset

    @require_validated
    def create_k8s_object_yamls(self, namespace: Metadata, seen_flows: set):
        """
        Create configs so we can deploy the appropriate PVC's and pull secrets
        for this edge's namespace.
        """
        obj_list = []
        if self.flow.need_pv():
            obj_list.extend(super().create_k8s_object_yamls(namespace, seen_flows))
        if not self._edge_secret_created(seen_flows) and IMAGE_PULL_SECRET_PATH:
            try:
                with open(IMAGE_PULL_SECRET_PATH, "rb") as f:
                    dockerconfigjson = str(base64.b64encode(f.read()), "utf-8")
            except FileNotFoundError:
                raise DeploymentError(
                    {"Image pull secret path is given but file does not exist. "
                     "This is a Rampart controller error; please report this bug."})
            obj_list.append(image_pull_secret_template(self._image_pull_secret_name,
                                                       dockerconfigjson, to_dict=True))
        return obj_list

    @require_validated
    def post_deploy_hooks(self, namespace: Metadata, seen_flows: set):
        """
        Call the parent class's post_deploy_hooks if appropriate
        """
        if self.flow.need_pv():
            return super().post_deploy_hooks(namespace, seen_flows)
        return []

    @staticmethod
    def _edge_secret_created(seen_flows: set):
        """Helper function to check whether required secrets are already created for
        this edge.
        Since all edges of one component exists in the same namespace, only one set
        of secret is needed.
        """
        for flow in seen_flows:
            if flow.type is FlowType.REPOSITORY:
                return True
        return False
