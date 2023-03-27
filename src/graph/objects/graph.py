# Copyright 2023 Petuum, Inc. All Rights Reserved.

import asyncio
import collections
import copy
import itertools
import logging
import os
import pathlib
import shutil
from typing import List

import aiofiles
import aiofiles.os
import aiohttp
import kubernetes_asyncio as kubernetes

from ..constants import (COMPONENT_INSTALL_TIMEOUT, GENERATE_PULSAR_NAMESPACE,
                         HNS_API, HNS_KIND_PL, HNS_VERSION, HTTP_TIMEOUT,
                         JSONSCHEMA_VALIDATOR, LOGGING_FORMAT,
                         PULSAR_ADMIN_SERVICE, PULSAR_TENANT, RAMPART_CRD_API,
                         AUX_CHART_REPO, AUX_CHART_NAME, AUX_CHART_VERSION,
                         AUX_CHART_COMP_KEY,
                         RAMPART_CRD_KIND, RAMPART_CRD_VERSION)
from .base_types import BaseElement, Metadata, KubernetesName
from .component import ComponentInstance
from .component_chart import ComponentChart
from .edge import FlowType, Flow, PVFlow, RepositoryFlow
from ..k8s_templates import owner_reference_template
from ..repository import get_global_repo_manager
from ..utils import deployment as deployment_util
from ..utils.classes import (DeploymentError, GraphPhase, ValidationError,
                             collect_errors, validate_dict)
from ..utils.deployment import require_validated
from ..utils.infra import apply_infra_object, pulsar_enabled
from ..utils.logger import GraphLogger

try:
    from yaml import CLoader as Loader
    from yaml import dump, load
except ImportError:
    from yaml import Loader, dump, load


kubernetes.config.load_incluster_config()
core_api = kubernetes.client.CoreV1Api()
apps_api = kubernetes.client.AppsV1Api()
custom_api = kubernetes.client.CustomObjectsApi()

logging.basicConfig(format=LOGGING_FORMAT)
LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)


class Graph(BaseElement):
    """
    This graph manages all of the validation, deployment, and teardown for a single rampart graph.
    """
    def __init__(self,
                 metadata,
                 pulsar_namespace,
                 components_dict=None,
                 component_charts=None,
                 flows=None,
                 deploy=True,
                 workdir=""):
        super().__init__(metadata)
        self._metadata = metadata
        self._logger = GraphLogger(LOG, {"metadata": metadata})
        self._filename = f"{metadata.name}_helmfile.yaml"
        self._components = components_dict or {}
        self._component_charts = component_charts or {}
        # Note: "_" cannot occur in custom resource names
        self._pulsar_namespace = pulsar_namespace
        self._flows = flows or {}
        self._workdir = workdir
        self._deployed_components = {}
        self._deployed_flows = {}
        self._deploy = deploy

        # TODO: edge -> component
        self._edge_helm_dir = os.path.join(workdir, f"{metadata.name}_edges_helm")

        self._owner_reference = owner_reference_template(self.name, self.uid, RAMPART_CRD_KIND,
                                                         RAMPART_CRD_API)

    @staticmethod
    async def _build_aux_chart(graph_json, component_charts, metadata):
        """
        produces the hidden aux-chart based on default spec
        """
        logger = GraphLogger(LOG, {"metadata": metadata})
        aux_chart = None
        aux_chart_dict = {
            "repo": AUX_CHART_REPO,
            "name": AUX_CHART_NAME,
            "version": AUX_CHART_VERSION,
            "values": None
        }
        for component in graph_json["components"].values():
            if "ingressNeeded" in component and component["ingressNeeded"]:
                if AUX_CHART_COMP_KEY not in component_charts:
                    aux_chart = await ComponentChart.from_yaml(aux_chart_dict, metadata)
                    if aux_chart:
                        component_charts[AUX_CHART_COMP_KEY] = aux_chart
        logger.info(f"build aux-chart into component_charts: aux_chart = {aux_chart}")
        return aux_chart

    @classmethod
    async def _parse_json(cls, json_obj, metadata, validate_specs=True):
        """
        Class function to turn a json object into a a set of components, component charts,
        flows, and a boolean for whether the graph is to be deployed

        args:
            json_obj: dictionary for the kubernetes values for the graph
            metadata (basetype.Metadata): namespace, name, uid for the graph
            validate_specs (bool): whether to pull from the remote helm repos. set to false
        """
        logger = GraphLogger(LOG, {"metadata": metadata})

        graph_json = json_obj['graph']
        deploy = json_obj.get('deploy', True)

        flow_dict = {}
        for io_name, properties in graph_json["flows"].items():
            io_type = FlowType[properties["type"].upper()]
            io_config = properties.get("config", {})
            flow_dict[io_name] = Flow.create(io_name, io_type, io_config, metadata)

        components_dict = {}
        component_charts = {}
        # build aux-chart based on graph spec
        aux_chart = await cls._build_aux_chart(graph_json, component_charts, metadata)

        # Generate component instance objects for each of the components, and then generate
        # component chart objects as necessary
        for comp_inst_name, component in graph_json["components"].items():
            logger.info(f"found component {comp_inst_name}", extra={"phase": GraphPhase.PARSING})
            comp_uid = ComponentInstance.generate_name(
                metadata.namespace.kubernetes_view,
                metadata.name.kubernetes_view,
                KubernetesName(comp_inst_name).kubernetes_view)
            if "namespace" in component and component["namespace"]:
                comp_inst_namespace = component["namespace"]
            else:
                comp_inst_namespace = comp_uid
            comp_inst_metadata = Metadata(comp_inst_namespace, comp_inst_name, comp_uid)

            component_chart_key = ComponentChart.generate_key(component["chart"])

            if component_chart_key not in component_charts:
                component_charts[component_chart_key] = await ComponentChart.from_yaml(
                    component["chart"], metadata)

            component_chart = component_charts[component_chart_key]

            # aux-chart is an optional, hidden chart managed by rampart
            aux_chart_inst = None
            if "ingressNeeded" in component and component["ingressNeeded"]:
                aux_chart_inst = aux_chart

            components_dict[comp_inst_metadata.kubernetes_view] = ComponentInstance(
                comp_inst_metadata, component,
                metadata, component_chart, flow_dict, aux_chart=aux_chart_inst)
        logger.info(f"component charts: {component_charts}", extra={"phase": GraphPhase.PARSING})

        errors = []

        namespaces_result = await core_api.list_namespace()
        namespaces = namespaces_result.items

        graphs_result = await custom_api.list_cluster_custom_object(
            "rampart.petuum.com", RAMPART_CRD_VERSION, "rampartgraphs")
        graphs = graphs_result["items"]

        preexisting_namespaces = {namespace.metadata.name for namespace in namespaces}

        # Generate the list of namespaces we manage excluding the namespaces added by this graph
        for graph in graphs:
            if (graph["metadata"]["name"] != metadata.name.kubernetes_view or
                    graph["metadata"]["namespace"] != metadata.namespace.kubernetes_view):
                for component_name, component in graph["spec"]["graph"]["components"].items():
                    if "namespace" in component:
                        preexisting_namespaces.add(component["namespace"])
                    else:
                        preexisting_namespaces.add(ComponentInstance.generate_name(
                            graph["metadata"]["namespace"],
                            graph["metadata"]["name"],
                            component_name))
            # If we enter here during the validating webhook,
            # we are doing an update to an existing graph.
            # Note: we don't care about the order of this removal w/r to the previous additions
            # as the graphs must not have overlapping namespaces for them to have been created
            # already
            else:
                for component_name, component in graph["spec"]["graph"]["components"].items():
                    if "namespace" in component:
                        namespace = component["namespace"]
                    else:
                        namespace = ComponentInstance.generate_name(
                            graph["metadata"]["namespace"],
                            graph["metadata"]["name"],
                            component_name)
                    if namespace in preexisting_namespaces:
                        preexisting_namespaces.remove(namespace)

        # Here we check that there are no namespace overlaps between the components in this graph
        # and from other graphs, and that all of the infrastructure requirements of this graph are
        # met
        for comp_inst_name, component in components_dict.items():
            if component.metadata.namespace.kubernetes_view in preexisting_namespaces:
                errors.append(f"Namespace {component.metadata.namespace.kubernetes_view} "
                              "already exists.")
            for component_needs in component.body.get("needs", []):
                component_needs_name = KubernetesName(component_needs)
                try:
                    needed_component = components_dict[component_needs_name.kubernetes_view]
                except KeyError:
                    errors.append(f"Component {component_needs} needed by {comp_inst_name} "
                                  "does not exist.")
                # TODO: automatically append to needs according to provide/required.
                component.needs.append(f"{needed_component.uid}/component")
        if errors:
            raise ValidationError(errors)
        return components_dict, component_charts, flow_dict, deploy

    @classmethod
    async def from_json(cls, graph_json, metadata, validate_specs=True, workdir: str = ""):
        """
        Return a Graph object from the specified json (generally the json found
        in a RampartGraph CRD).

        args:
            graph_json: dictionary object representing all the specifications of the graph
            metadata (basetype.Metadata): namespace, name, uid for the graph
            validate_specs (bool): whether to pull from the remote helm repos. set to false
                                   when validation time is critical
            workdir (str): path to a temporary directory to store output for helm and helmfile
        """
        logger = GraphLogger(LOG, {"metadata": metadata})
        logger.info("beginning parsing", extra={"phase": GraphPhase.PARSING})

        errors = JSONSCHEMA_VALIDATOR.iter_errors(graph_json)

        def format_validation_error(errors, depth):
            """ Returns errors indented by subschema and delimited. """
            res = ""
            for error in errors:
                # Use jsonschema's error formatting minus the extra newlines
                # https://github.com/python-jsonschema/jsonschema/blob/main/jsonschema/exceptions.py#L67
                for line in str(error).split('\n'):
                    if line:
                        res += depth * '\t' + line + "\n"
                res += depth * '\t' + '-' * 75 + '\n'
                res += format_validation_error(error.context, depth + 1)
            return res
        error_output = format_validation_error(errors, 0)
        if error_output:
            raise ValidationError({error_output})

        logger.info("schema validated", extra={"phase": GraphPhase.PARSING})

        pulsar_namespace = GENERATE_PULSAR_NAMESPACE(metadata)

        components_dict, component_charts, flows, deploy = await cls._parse_json(
            graph_json, metadata, validate_specs)
        await get_global_repo_manager().update_provides()

        workdir = os.path.join(
            workdir,
            metadata.namespace.rampart_view + "_" + metadata.name.rampart_view)
        return Graph(metadata,
                     pulsar_namespace=pulsar_namespace,
                     components_dict=components_dict,
                     component_charts=component_charts,
                     flows=flows,
                     deploy=deploy,
                     workdir=workdir)

    async def validate(self, validate_specs):
        """
        Throws a `ValidationError` if the graph is invalid. This call must be made
        before any function with the `@required_validated` decorator is called.

        args:
            validate_specs (Bool):
                True -> Pull the helm charts for this graph and validate with all the
                        Rampart component specification there. This may be expensive,
                        so only use this flag when time is not of the essence. For example,
                        validating webhooks have a non-bypassable timeout limit
                False -> Do not pull the helm charts
        """
        errors = []

        try:
            self._logger.info("validating components", extra={"phase": GraphPhase.VALIDATION})
            await validate_dict(self._components, validate_specs=validate_specs)

        except ValidationError as e:
            errors.extend(e.errors)

        if errors:
            raise ValidationError(errors)

        await validate_dict(self._flows)

        if validate_specs:
            self._logger.info("validating provided and requirements",
                              extra={"phase": GraphPhase.VALIDATION})
            provided = get_global_repo_manager().provided
            source = {"namespace": self._metadata.namespace.kubernetes_view,
                      "name": self._metadata.name.kubernetes_view}
            for component_chart in self._component_charts.values():
                component_spec = component_chart.component_spec
                metadata = component_spec.metadata
                duplicate = [comp_provided for comp_provided in component_spec.provides
                             if comp_provided in provided and provided[comp_provided] != source]
                if duplicate:
                    errors.append(
                        f"Component chart {metadata.name}"
                        "provides duplicate/conflicting infrastructure"
                        f" {duplicate}")
                provided.update({infra: source for infra in component_spec.provides})

            self._logger.info(f"found infrastructure dependencies: {provided}",
                              extra={"phase": GraphPhase.VALIDATION})

            for chart_name, component_chart in self._component_charts.items():
                component_spec = component_chart.component_spec
                metadata = component_spec.metadata
                self._logger.info(f"component chart {chart_name} "
                                  f"requires: {component_spec.requires}",
                                  extra={"phase": GraphPhase.VALIDATION})
                not_provided = [
                    required for required in component_spec.requires
                    if required not in provided]
                if not_provided:
                    self._logger.info(f"requirements that have not been found: {not_provided}",
                                      extra={"phase": GraphPhase.VALIDATION})
                    errors.append(
                        f"Component chart {metadata.name} requires infrastructure "
                        f"{not_provided} to be installed. Please ensure you have "
                        "a graph providing those dependencies installed on your cluster")

        component_flow_names = dict()
        component_namespaces = dict()
        for component in self._components.values():
            name = component.name
            namespace = component.metadata.namespace
            if namespace.kubernetes_view in component_namespaces:
                errors.append(
                    f"components '{name.original_view}' and "
                    f"'{component_namespaces[namespace.kubernetes_view]}' have an overlapping "
                    f"namespace '{namespace.original_view}'")
            else:
                component_namespaces[namespace.kubernetes_view] = name.original_view

            if name.kubernetes_view in component_flow_names:
                errors.append(
                    f"Component name {name.original_view} overlaps with component or flow name "
                    f"{component_flow_names[name.kubernetes_view]}.")
            else:
                component_flow_names[name.kubernetes_view] = name.original_view
        # Due to the frontend limitations
        for flow in self._flows.values():
            name = flow.name
            if "aabbccdd" in name.kubernetes_view:
                errors.append(
                    f"Flow name {name.original_view} overlaps with aabbccdd")
            if name.kubernetes_view in component_flow_names:
                errors.append(
                    f"Flow name {name.original_view} overlaps with component or flow name "
                    f"{component_flow_names[name.kubernetes_view]}.")
            else:
                component_flow_names[name.kubernetes_view] = name.original_view

        if errors:
            raise ValidationError(errors)

        self._validated = True

    @property
    def namespaces(self):
        """Returns a list of namespaces for the graph's components"""
        return [component.namespace.name.kubernetes_view if component.namespace else
                component.metadata.namespace.kubernetes_view
                for component in self._components.values()]

    @property
    def namespace_to_component_map(self):
        """One to one map between namespace and component name"""
        return {component.namespace.name.kubernetes_view if component.namespace else
                component.metadata.namespace.kubernetes_view: component.metadata.name.original_view
                for component in self._components.values()}

    @property
    def owner_reference(self):
        return self._owner_reference

    @property
    def to_deploy(self):
        return self._deploy

    @property
    @require_validated
    def provided(self):
        """Returns a list of infrastructure that this graph provides"""
        provided = set()
        for component_chart in self._component_charts.values():
            component_spec = component_chart.component_spec
            provided.update(component_spec.provides)
        return provided

    @require_validated
    async def _deploy_namespaces(self) -> None:
        """Deploys the component namespaces for this graph"""
        self._logger.info(
            "deploying namespaces", extra={"phase": GraphPhase.DEPLOYMENT})
        # TODO: find an appropriate ownerref anchor for the subnamespace
        # that doesnt introduce race conditions with helm uninstall
        sub_namespace_tasks = [comp.deploy_sub_namespace(self._metadata.namespace,
                                                         self._owner_reference)
                               for comp in self._components.values()]
        results = await asyncio.gather(*sub_namespace_tasks, return_exceptions=True)
        collect_errors(results)

    @require_validated
    async def _deploy_edges(self) -> List[asyncio.Task]:
        """
        Deploys all the edges and flows for this graph.
        Return a list of tasks that need finishing at some later point.
        """
        self._logger.info(
            "deploying edges and flows", extra={"phase": GraphPhase.DEPLOYMENT})
        # group flows by their types
        flows_by_type = collections.defaultdict(list)
        for flow in self._flows.values():
            flows_by_type[flow.type].append(flow)

        async def batch_deploy_flow_type(flow_type, flows):
            self._logger.info(
                f"deploying {flow_type}", extra={"phase": GraphPhase.DEPLOYMENT})
            workdir = os.path.join(self._workdir, "flows", flow_type.name)
            return await flows[0].batch_deploy(flows, workdir, self._metadata)
        running_tasks = await asyncio.gather(*[
            batch_deploy_flow_type(flow_type, flows) for flow_type, flows in flows_by_type.items()],
            return_exceptions=True)
        collect_errors(running_tasks)
        running_tasks = list(itertools.chain(*running_tasks))
        self._deployed_flows = copy.copy(self._flows)

        helm_init_args = [
            "helm", "create",
            self._edge_helm_dir, "-p",
            os.path.join(pathlib.Path(__file__).parent.parent.absolute(), "base_component_chart")]
        await deployment_util.required_subprocess(self._metadata, True, None, *helm_init_args)

        return running_tasks

    @require_validated
    async def _deploy_components(self, helmfile_args=None, helmfile_kwargs=None):
        """
        Deploys all the components for this graph.

        Generates helmfile configs in `workdir`, and then calls `helmfile sync` on the files
        """
        self._logger.info(
            "deploying components", extra={"phase": GraphPhase.DEPLOYMENT})
        helmfile_args = helmfile_args or []
        helmfile_kwargs = helmfile_kwargs or {}
        repository_yaml = {
            comp_chart.repo.name:
            {"name": comp_chart.repo.name, "url": comp_chart.repo.url,
             **comp_chart.pull_keys}
            for comp_chart in self._component_charts.values()}
        repository_yaml = list(repository_yaml.values())
        release_yaml = []
        remaining_tasks = []
        for component in self._components.values():
            releases, tasks = await component.to_deployment_yaml(self._workdir)
            release_yaml.extend(releases)
            remaining_tasks.extend(tasks)

        yaml = {"repositories": repository_yaml,
                "releases": release_yaml,
                "helmDefaults": {
                    "recreatePods": False,
                    "wait": True,
                    "timeout": COMPONENT_INSTALL_TIMEOUT}}
        filename = os.path.join(self._workdir, self._filename)
        # The yamlfile must be overwritten in case of redeployment
        async with aiofiles.open(filename, "w") as yaml_file:
            await yaml_file.write(dump(yaml, width=float("inf")))

        # helmfile deployment manages deployment with an upgraded graph or
        # previous partial deployment

        deploy_args = ["helmfile", "--file", filename, "sync", "--args",
                       '"--debug"']
        deploy_args += helmfile_args
        for key, value in helmfile_kwargs.items():
            deploy_args += [key, value]
        env = copy.deepcopy(dict(os.environ))
        env["RAMPART_WORKDIR"] = self._workdir
        for component in self._components.values():
            env[f"RAMPART_{component.name}_namespace"] = component.namespace.name.kubernetes_view
        if yaml["releases"]:
            await deployment_util.required_subprocess(
                self._metadata, True, self._clean_up_callback(release_name="component"),
                *deploy_args, env=env)
        await asyncio.gather(*[task for task in remaining_tasks])
        self._deployed_components = copy.copy(self._components)
        self._logger.info(
            "components deployed", extra={"phase": GraphPhase.DEPLOYMENT})

    @require_validated
    async def deploy(self, helmfile_args=None, helmfile_kwargs=None) -> None:
        """Deploys the namespaces, edges, and then components for this graph"""
        if not self._deploy:
            raise TypeError("Cannot deploy a graph with field `deploy: false`")
        await deployment_util.required_deploy(self._deploy_namespaces)

        async def handle_task(task: asyncio.Task):
            """Simply raise errors if any."""
            await task
            task.result()
        remaining_tasks = [
            handle_task(task)
            for task in await deployment_util.required_deploy(self._deploy_edges)]
        results = await asyncio.gather(
            *(remaining_tasks +
              [deployment_util.required_deploy(
                  self._deploy_components, helmfile_args or [], helmfile_kwargs or {})]),
            return_exceptions=True)
        collect_errors(results, error_cls=DeploymentError)
        await apply_infra_object(self.metadata, self.provided, "deployed")

    @require_validated
    async def undeploy(self):
        """If the `deploy` field is set to false, we perform teardown on the graph deployment"""
        if self._deploy:
            raise TypeError("Cannot undeploy a graph with field `deploy: true`")
        await self.teardown_namespaces(self.namespaces)
        await PVFlow.batch_teardown(self.metadata)
        await RepositoryFlow.batch_teardown(self.metadata)
        await apply_infra_object(self.metadata, set(), "deployed")

    @require_validated
    async def teardown_old_namespaces(self, old_namespace_list):
        """We need to manually tear down namespaces that no longer are part of the graph"""
        current_namespaces = set(self.namespaces)
        return await self.teardown_namespaces(
            [namespace for namespace in old_namespace_list if namespace not in current_namespaces])

    async def teardown_namespaces(self, namespaces):
        """Tears down all the provided namespaces"""
        self._logger.info(
            f"uninstalling {namespaces}", extra={"phase": GraphPhase.TEARDOWN})
        await asyncio.gather(
            *[deployment_util.optional_subprocess(
                self._metadata, False, None,
                "helm", "uninstall", "-n", namespace, "component", "--wait")
              for namespace in namespaces])
        for namespace in namespaces:
            await deployment_util.optional_teardown(
                custom_api.delete_namespaced_custom_object,
                lambda e: type(e) == kubernetes.client.rest.ApiException,
                HNS_API, HNS_VERSION, self._metadata.namespace.kubernetes_view, HNS_KIND_PL,
                namespace)

    def _clean_up_callback(self, release_name):
        """Returns a function to clean up helm on deployment cancellation"""
        assert release_name in ["component", "edges"]

        # TODO: run helm rollback with timeout before falling back to uninstall
        async def callback():
            self._logger.info(f"deployment cancelled, cleaning up {self.namespaces}",
                              extra={"phase": GraphPhase.TEARDOWN})
            # TODO: add a rollback attempt before the uninstall
            await asyncio.gather(
                *[deployment_util.required_subprocess(
                    self._metadata, False, None,
                    "helm", "uninstall", "-n", namespace, release_name, "--wait")
                  for namespace in self.namespaces],
                return_exceptions=True)

            # This teardown needs to occur when current deployment has created a new component
            # namespace the previous deployment did not have.
            for namespace in self.namespaces:
                if namespace not in self._deployed_components:
                    await deployment_util.optional_teardown(
                        custom_api.delete_namespaced_custom_object,
                        lambda e: type(e) == kubernetes.client.rest.ApiException,
                        HNS_API, HNS_VERSION, self._metadata.namespace.kubernetes_view, HNS_KIND_PL,
                        namespace)
        return callback

    @classmethod
    async def remove_orphaned_pulsar(cls, graph_namespaces):
        """Delete all pulsar namespaces for graphs that have been deleted"""
        # TODO: we can probably remove this
        try:
            logger = GraphLogger(LOG, {"metadata": None})
            async with aiohttp.ClientSession(timeout=HTTP_TIMEOUT) as session:
                async with session.get(
                        f"http://{PULSAR_ADMIN_SERVICE}/admin/v2/tenants/") as resp:
                    if resp.status == 200:
                        tenants = await resp.json()
                        if PULSAR_TENANT not in set(tenants):
                            return
                    elif resp.status == 403:
                        raise DeploymentError({
                            "The rampart controller does not have admin access"
                            "to the pulsar deployment."})
                    elif resp.status >= 400 and resp.status < 500:
                        raise DeploymentError({
                            f"Recieved {resp.status} while getting pulsar tenants"})
                async with session.get(
                        f"http://{PULSAR_ADMIN_SERVICE}/admin/v2/namespaces/{PULSAR_TENANT}"
                ) as resp:
                    if resp.status == 200:
                        text = await resp.text()
                        namespaces = set(
                            [namespace.split("/")[-1] for namespace in load(text, Loader=Loader)])
                        for graph_namespace in namespaces:
                            if graph_namespace not in graph_namespaces:
                                logger.info(
                                    f"deleting pulsar namespace: {graph_namespace}",
                                    extra={"phase": GraphPhase.TEARDOWN})
                                async with session.delete(
                                        f"http://{PULSAR_ADMIN_SERVICE}/admin/v2/namespaces/"
                                        f"{PULSAR_TENANT}/{graph_namespace}?force=true") as resp:
                                    if resp.status >= 300 and resp.status != 404 \
                                            and resp.status != 409:
                                        text = await resp.text()
                                        raise DeploymentError(
                                            {"Cannot delete Pulsar namespace: "
                                             f"[{resp.status}] {text}"})
        except (aiohttp.ClientConnectionError, asyncio.TimeoutError):
            logger.info(
                "pulsar is enabled but its service is not available yet.",
                extra={"phase": GraphPhase.NONE})

    @classmethod
    async def teardown(cls, metadata, workdir) -> None:
        """Tear down all the deployed objects for a graph"""
        repo_manager = get_global_repo_manager()
        repo_manager_gc_task = repo_manager.gc_graph(metadata)

        clean_workdir_task = deployment_util.optional_teardown(
            aiofiles.os.wrap(shutil.rmtree), lambda e: type(e) == FileNotFoundError,
            os.path.join(
                workdir, metadata.namespace.rampart_view + "_" + metadata.name.rampart_view))

        logger = GraphLogger(LOG, {"metadata": metadata})

        async def clean_pulsar():
            try:
                async with aiohttp.ClientSession(timeout=HTTP_TIMEOUT) as session:
                    async with session.delete(
                            f"http://{PULSAR_ADMIN_SERVICE}/admin/v2/namespaces/"
                            f"{GENERATE_PULSAR_NAMESPACE(metadata)}?force=true") as resp:
                        if resp.status >= 300 and resp.status != 404 and resp.status != 409:
                            text = await resp.text()
                            raise DeploymentError(
                                {f"Cannot delete Pulsar namespace: [{resp.status}] {text}"})
            except (aiohttp.ClientConnectionError, asyncio.TimeoutError):
                pass
                logger.info(
                    "Cannot remove pulsar flows: "
                    "Pulsar is enabled but its service is not available yet.",
                    extra={"phase": GraphPhase.TEARDOWN})

        if pulsar_enabled():
            await asyncio.gather(repo_manager_gc_task, clean_workdir_task, clean_pulsar())
        else:
            await asyncio.gather(repo_manager_gc_task, clean_workdir_task)
