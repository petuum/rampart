# Copyright 2023 Petuum, Inc. All Rights Reserved.

import aiofiles
import copy
import itertools
import kubernetes_asyncio as kubernetes
import logging
import os
import yaml
import yaml.scanner

from .edge import Edge, EdgeType, IOPart, VariadicEdgeSpec
from .base_types import BaseElement
from ..k8s_templates import config_map_mount, config_map_template, preset_template
from ..utils import deployment as deployment_util
from ..utils.classes import GraphPhase, ValidationError, Either
from ..utils.deployment import require_validated
from ..utils.logger import GraphLogger
from ..utils.tree_utils import recursive_merge
from ..utils.tycheck import has_shared_prefix
from ..utils.yaml_utils import yaml

from ..constants import HNS_API, HNS_VERSION, HNS_KIND_PL, LOGGING_FORMAT, RAMPART_REGISTRY, \
                        VOLUME_FLOW_LIVENESS_PATH

kubernetes.config.load_incluster_config()
custom_api = kubernetes.client.CustomObjectsApi()
core_api = kubernetes.client.CoreV1Api()

logging.basicConfig(format=LOGGING_FORMAT)
LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)


def _match_variadic_spec_by_name(specs, name):
    """Return the longest prefix match against edge spec name."""
    match = None
    length = -1
    for val in specs.values():
        if isinstance(val, VariadicEdgeSpec):
            if val.matches(name) and len(val.prefix) > length:
                match = val
                length = len(val.prefix)
    return match


class ComponentInstance(BaseElement):
    """
    This class contains the functionality for a single component instance within a graph.

    This is primarily validation within the component instance, any (un)deployment tasks that
    can be fully contained within this instance, and passing necessary information
    (such as helmfile configs) back to the parent graph object.
    """
    def __init__(self, metadata, body, graph_metadata, comp_chart, flows, needs=None,
                 aux_chart=None,
                 deployment_kwargs=None):
        super().__init__(metadata)

        self._body = body
        self._graph_metadata = graph_metadata
        self._chart = comp_chart
        self._comp_spec = None
        self._inputs = {}
        self._outputs = {}
        self._edge_helm_file = None
        self._namespace = None  # Metadata instance
        self._modified_edge = False
        self._flows = flows
        self._needs = needs or []
        self._deployment_kwargs = deployment_kwargs or {}
        self._edges_helm_chart = f"{graph_metadata.name}_edges_helm"
        self._aux_chart = aux_chart

        self._logger = GraphLogger(LOG, {"metadata": graph_metadata})

        def _get_edges(yaml_obj, part):
            edges = {}
            for key, value in yaml_obj.items():
                flow_name = value["flow"]
                edge_type = EdgeType[value["type"].upper()]
                edge_config = value.get("config", {})
                if flow_name in flows:
                    flow = Either.Success(flows[flow_name])
                else:
                    flow = Either.Failure(flow_name)
                edges[key] = Edge.create(key, edge_type, part, edge_config, flow,
                                         self._graph_metadata, self._metadata)
            return edges

        self._inputs = _get_edges(body["inputs"], IOPart.INPUT)
        self._outputs = _get_edges(body["outputs"], IOPart.OUTPUT)

    @staticmethod
    def generate_name(graph_namespace, graph_name, component_name):
        return f"{graph_namespace}-{graph_name}-{component_name}"

    @property
    def body(self) -> dict:
        return copy.deepcopy(self._body)

    @property
    def inputs(self) -> dict:
        return self._inputs

    @property
    def outputs(self) -> dict:
        return self._outputs

    @property
    def namespace(self):
        return self._namespace

    @property
    def needs(self):
        return self._needs

    async def validate(self, validate_specs=True):
        """
        Throws a `ValidationError` if the component is invalid. This call must be made
        before any function with the `@required_validated` decorator is called.

        args:
            validate_specs (Bool):
                True -> Pull the helm chart for this component and validate with all the
                        Rampart component specification there. This may be expensive,
                        so only use this flag when time is not of the essence. For example,
                        validating webhooks have a non-bypassable timeout limit
                False -> Do not pull the helm chart
        """
        if validate_specs:
            await self._chart.validate()
            if self._aux_chart:
                self._logger.info(f"validating: aux_chart = {self._aux_chart}")
                await self._aux_chart.validate()
            self._comp_spec = self._chart.component_spec
        errors = []

        if self.name.kubernetes_view == "rampart-flows":
            raise ValidationError({"'rampart-flows' is not allowed as a component name"})

        async def _validate_edges(target: dict, target_spec: dict):
            """
            Function to generalize the code for both input and output edges
            """
            for name, edge in target.items():
                io_type = edge.type
                flow = edge.flow
                if target_spec is not None:
                    if name in target_spec:
                        spec = target_spec[name]
                    else:
                        spec = _match_variadic_spec_by_name(target_spec, name)
                    try:
                        await edge.validate(spec)
                    except ValidationError as err:
                        errors.extend(err.errors)
                if not flow:
                    errors.append(
                        f"{edge.part.name.capitalize()} {name} with type {io_type.name} uses flow "
                        f"{edge.flow_name} which does not exist")
                elif io_type is not flow.type:
                    errors.append(
                        f"{edge.part.name.capitalize()} {name} with type {io_type.name} "
                        f"does not match flow type {flow.type.name}")
                else:
                    try:
                        await flow.validate()
                    except ValidationError as err:
                        errors.extend(err.errors)

        if validate_specs:
            if not self._comp_spec.validated:
                raise ValidationError({
                    f"ComponentSpec {self._comp_spec.name} is not validated. "
                    f"This is a Rampart controller error; please report this bug."})

            if self.name == "rampart-flows":
                raise ValidationError({"'rampart-flows' is not allowed as a component name"})

            await _validate_edges(self._inputs, self._comp_spec.input_specs)
            await _validate_edges(self._outputs, self._comp_spec.output_specs)

        else:
            await _validate_edges(self._inputs, None)
            await _validate_edges(self._outputs, None)

        edge_names = dict()
        for edge in (list(self._inputs.values()) + list(self._outputs.values())):
            name = edge.name
            if name.kubernetes_view in edge_names:
                errors.append(
                    f"Edge name {name.original_view} overlaps with another edge name "
                    f"{edge_names[name.kubernetes_view]}.")
            else:
                edge_names[name.kubernetes_view] = name.original_view

        # TODO: remove the this edge type dependency
        mounts = [edge.mount_path for edge in
                  (list(self._inputs.values()) + list(self._outputs.values()))
                  if hasattr(edge, "mount_path") and edge.mount_path is not None]
        if has_shared_prefix(mounts):
            errors.append(f"Volume input and output paths cannot be prefixes of another: {mounts}")

        if errors:
            raise ValidationError(errors)

        self._validated = True

    @require_validated
    async def to_deployment_yaml(self, workdir):
        """
        Creates the helmfile files for the edges, returns the helmfile configurations for deploying
        this component chart, and returns a list of tasks for deploying edges that the graph will
        need to see through to completion
        """
        edge_release_yaml, edge_tasks = await self.create_edges(workdir, self._edges_helm_chart)
        # TODO: Add unit tests
        # A dictionary of values that are passed to the component helm charts.
        # The components may use them as {{ .Values.rampart.namespace }}
        # or in subcharts as             {{ .Values.global.rampart.namespace}}
        helm_edge_yamls = {"rampart": {
            "inputs": {},
            "outputs": {},
            "graphName": self._graph_metadata.name.kubernetes_view,
            "namespace": self._graph_metadata.namespace.kubernetes_view,
            "registry": RAMPART_REGISTRY,
            # suggest url prefix for component ingress. Component should be responsible
            # for appending proper suffixes when there are multiple services.
            "URLPrefix": (f"/{self._graph_metadata.namespace.kubernetes_view}"
                          f"/{self._graph_metadata.name.kubernetes_view}"
                          f"/{self.name.kubernetes_view}")
        }}
        for name, edge in self._inputs.items():
            helm_edge_yamls["rampart"]["inputs"][name] = edge.resource
        for name, edge in self._outputs.items():
            helm_edge_yamls["rampart"]["outputs"][name] = edge.resource
        helm_edge_yamls_copy = copy.deepcopy(helm_edge_yamls)
        helm_edge_yamls["global"] = helm_edge_yamls_copy
        values = self.body["config"]
        recursive_merge(helm_edge_yamls, values)
        comp_release_yaml = self._chart.to_deployment_yaml(
            "component",
            self.namespace,
            values, self._modified_edge, self._deployment_kwargs, self.needs + ["edges"])

        comp_chart_yamls = [edge_release_yaml, comp_release_yaml]

        # handle aux-chart
        aux_release_yaml = self._gen_aux_chart()
        if aux_release_yaml:
            comp_chart_yamls.append(aux_release_yaml)
        return comp_chart_yamls, edge_tasks

    @require_validated
    def _gen_aux_chart(self):
        """
        Creates a chart for auxiliary charts that are attached onto components.
        """
        aux_chart_yaml = None
        if self._aux_chart:
            aux_values = self.body["auxConfig"]

            aux_chart_yaml = self._aux_chart.to_deployment_yaml(
                "auth-aux",
                self.namespace,
                aux_values, self._modified_edge, self._deployment_kwargs, self.needs)
            self._logger.info(f"Generating aux_chart_yaml = {aux_chart_yaml}")
        return aux_chart_yaml

    @require_validated
    async def deploy_sub_namespace(self, base_namespace, owner_reference):
        """
        Deploys the namespace for this component,
        and sets up all the necessary ownerReferences for automatic deletion later
        """
        self._logger.info(
            ("deploying subnamespace for Component "
             f"{self.metadata.namespace.kubernetes_view}/"
             f"{self.metadata.name.kubernetes_view}"),
            extra={"phase": GraphPhase.DEPLOYMENT})
        self._namespace = await deployment_util.deploy_sub_namespace(
            self._metadata.namespace, base_namespace, owner_reference,
            custom_api, core_api, self._graph_metadata)
        return self._namespace

    @require_validated
    def _get_edge_helm_yamls(self):
        """
        Returns the configurations for helmfile to use to deploy the edges for this component.
        Includes:
            * The list of kubernetes objects that need to be created directly
            * The mutation preset that Rampart will use to modify component pods to attach edges
            * ConfigMaps for the edges
            * Hooks for the caller to finish for modifying deployed objects

        See src/graph/base_component_chart/templates/edges.yaml for where they are used
        """
        # TODO: Add unit tests
        edges = list(itertools.chain(self._inputs.values(), self._outputs.values()))
        k8s_objects = []
        post_deploy_hooks = []
        seen_flows = set()
        # TODO: Create Preset object to hold and merge preset deltas provided by edges
        preset = preset_template(self.name, self.namespace.name)
        config_map_body = []
        for edge in sorted(edges, key=lambda e: e.name):
            k8s_objects.extend(edge.create_k8s_object_yamls(self.namespace, seen_flows))
            post_deploy_hooks.extend(edge.post_deploy_hooks(self.namespace, seen_flows))
            recursive_merge(edge.create_pod_preset_values(seen_flows), preset, merge_list=True)
            seen_flows.add(edge.flow)

            # Used by the liveness service
            config_map_body.append(
                {"name": edge.name.rampart_view,
                 "type": str(edge.type), "part": str(edge.part)})

        # Attach config maps for the liveness services, so they can see the graph topology
        edge_config_map = config_map_template(
            self.name, self.namespace.name,
            {"component": self.name.kubernetes_view, "edges": yaml.dump(config_map_body)})
        config_map_preset = config_map_mount(
            self.name.kubernetes_view,
            {"component": "component.yaml", "edges": "edges.yaml"}, ".RAMPART")
        recursive_merge(config_map_preset, preset, merge_list=True)
        return (
            {"obj_list": k8s_objects, "preset": preset, "edge_config_map": edge_config_map},
            post_deploy_hooks)

    @require_validated
    async def _check_helm_modified(self, filename, edges_helm_name, helm_chart):
        """Determines if upgrading would result in changes to the cluster"""
        helm_diff_args = [
            "helm", "diff", "upgrade", "-n",
            self.namespace.name.kubernetes_view, edges_helm_name, helm_chart,
            "-f", filename, "--output", "json", "--allow-unreleased", '--detailed-exitcode']
        return_code, _, _ = \
            await deployment_util.subprocess_with_return_code(
                self._graph_metadata, [0, 2], True, None,
                *helm_diff_args)

        return return_code == 2

    @require_validated
    async def create_edges(self, workdir, helm_chart):
        """
        Writes helmfile configurations required to deploy the edges for this instance and
        creates hooks for the controller to run after the edges have been deployed.
        """
        # TODO: Add unit tests
        edge_yaml, hooks = self._get_edge_helm_yamls()
        async with aiofiles.open(VOLUME_FLOW_LIVENESS_PATH, "r") as f:
            app_source_file = await f.read()
        extra_values = {
            "graphNamespace": self._graph_metadata.namespace.kubernetes_view,
            "graphName": self._graph_metadata.name.kubernetes_view,
            "graphUID": self._graph_metadata.uid,
            "appSource": app_source_file}
        edge_yaml.update(extra_values)
        filename = f"{self.uid}_edge.yaml"
        self._edge_helm_file = os.path.join(workdir, filename)
        # Note: the following write must overwrite the existing one
        # in order for idempotency and graph update functionality to be maintained
        async with aiofiles.open(self._edge_helm_file, "w") as yaml_file:
            await yaml_file.write(yaml.dump(edge_yaml))
        helm_name = "edges"
        helmfile_yaml = {
            "name": helm_name,
            "namespace": self.namespace.name.kubernetes_view,
            "chart": helm_chart,
            "version": "0.0.0",
            "values": [filename]}
        helm_chart = os.path.join(workdir, helm_chart)
        filename = self._edge_helm_file
        # if the edge is modified, we will need to redeploy all the pods in the component namespace
        # so that they can pick up the changes.
        self._modified_edge = await self._check_helm_modified(filename, helm_name, helm_chart)
        return helmfile_yaml, hooks

    @require_validated
    async def deploy(self):
        """Actual deployment is provided by the `Graph` class"""
        pass

    @require_validated
    async def teardown(self, base_namespace):
        """Deletes/Undeploys any cluster resources specific for this component instance"""
        delete_args = [
            "helm", "-n", self.namespace.name.kubernetes_view,  "uninstall", "component"]
        await deployment_util.optional_subprocess(self._graph_metadata, False, None, *delete_args)

        if self._edge_helm_file:
            await deployment_util.optional_teardown(
                os.remove, lambda e: type(e) == FileNotFoundError,
                self._edge_helm_file)
        await deployment_util.optional_teardown(
            custom_api.delete_namespaced_custom_object,
            lambda e: type(e) == kubernetes.client.rest.ApiException,
            HNS_API, HNS_VERSION, base_namespace,
            HNS_KIND_PL, name=self.namespace.name.kubernetes_view)
