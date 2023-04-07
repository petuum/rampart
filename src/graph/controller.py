# Copyright 2023 Petuum, Inc. All Rights Reserved.

import asyncio
import collections
import json
import kubernetes_asyncio as kubernetes
import logging

from .constants import FINALIZER, LOGGING_FORMAT, RAMPART_CRD_VERSION, WORKDIR, \
    CONTROLLED_BY_RAMPART, APISIX_ROUTE_API, APISIX_ROUTE_VERSION, APISIX_ROUTE_KIND_PL, \
    PATCH_RETRY_TIMEOUT
from .objects.graph import Graph
from .objects.base_types import Metadata
from .repository import get_global_repo_manager
from .utils.classes import DeploymentError, GraphPhase, ValidationError
from .utils.deployment import merge_patch_namespaced_custom_object,\
    merge_patch_namespaced_custom_object_status
from .utils.infra import apply_infra_object, patch_ownerreference, pulsar_enabled
from .utils.logger import GraphLogger

logging.basicConfig(format=LOGGING_FORMAT)
LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)


"""
Due to the fact that this code is running in a pod on a Kubernetes cluster, this code
can be terminated at any time.

Therefore, we must maintain the invariant of idempotency throughout.
"""


class RampartController(object):

    def __init__(self):
        self._objs_api = kubernetes.client.CustomObjectsApi()
        self._network_api = kubernetes.client.NetworkingV1Api()
        self._custom_resource = ("rampart.petuum.com", RAMPART_CRD_VERSION, "rampartgraphs")
        self._queue = asyncio.Queue()

        # There can only have one deployment task per graph at a time,
        # so we use have a lock per graph uid to prevent simultaneous
        # deployment.
        self._deployment_locks = {}
        self._deployment_tasks = {}

        # We need to dynamically edit the locking set (within async tasks),
        # so we need a global lock on the locking set to prevent two different
        # tasks for the same graph creating two different locks
        self._deployment_lock = asyncio.Lock()

    async def run(self):
        """
        Spawn non-terminating tasks to watch changes to RampartGraph CR objects and update
        cluster state to match the specifications of the CR's.

        Also launch a garbage-collection task.
        """
        # FIXME: initialize allocations
        await asyncio.gather(
            self._watch_graphs(),
            self._remove_orphaned_graph_objects(),
            self._sync_graphs()
        )

    async def _patch_graph_status(self, namespace, name, patch_obj):
        """
        Patch the RampartGraph CR with the new values in patch_obj.
        Retries on failure up to a limit.

        Args:
            namespace (str): namespace of the CR
            name (str): name of the CR
            patch_obj (dict): changes to make to the CR
        """
        remaining = PATCH_RETRY_TIMEOUT
        while remaining >= 0.0:
            try:
                return await merge_patch_namespaced_custom_object_status(
                    self._objs_api, "rampart.petuum.com", RAMPART_CRD_VERSION, namespace,
                    "rampartgraphs", name, patch_obj)
            except kubernetes.client.rest.ApiException as exc:
                exception = exc
                await asyncio.sleep(1.0)
                remaining -= 1.0
        raise exception

    async def _watch_graphs(self):
        """
        A non-terminating function that watches changes to RampartGraph CR's across
        the entire cluster and appends the CR metadata and a deployment task to make the
        appropriate changes for the CR to a queue.
        """
        async with kubernetes.watch.Watch() as watch:
            while True:
                async for event in watch.stream(
                        self._objs_api.list_cluster_custom_object,
                        *self._custom_resource, timeout_seconds=60):
                    graph_name = event["object"]["metadata"]["name"]
                    namespace = event["object"]["metadata"]["namespace"]
                    uid = event["object"]["metadata"]["uid"]
                    graph_metadata = Metadata(namespace, graph_name, uid)
                    task = asyncio.create_task(self._sync_graph(graph_metadata))
                    await self._queue.put(task)

    async def _remove_orphaned_graph_objects(self):
        """
        A non-terminating function that deletes orphaned objects that are not managed via
        kubernetes owner-references.
        """
        while True:
            existing_graphs = await self._objs_api.list_cluster_custom_object(
                *self._custom_resource)
            graph_names = [graph["metadata"]["namespace"] + "_" + graph["metadata"]["name"]
                           for graph in existing_graphs["items"]]
            await get_global_repo_manager().update_provides()
            if pulsar_enabled():
                await Graph.remove_orphaned_pulsar(graph_names)
            await asyncio.sleep(60)

    async def _sync_graphs(self):
        """A non-terminating function that executes the deployment tasks from _watch_graphs"""
        while True:
            task = await self._queue.get()
            await task
            if exception := task.exception():
                LOG.error(str(exception))
            self._queue.task_done()

    async def _sync_graph(self, metadata):
        """
        This function wraps the tasks that do the actual work of updating the cluster
        to manage waiting for completion and cancellation.

        Args:
            metadata (objects.base_type.Metadata): metadata of the RampartGraph CR
        """

        # Ensure that only one task can update the state of deployment_locks at a time
        async with self._deployment_lock:
            if metadata.uid not in self._deployment_locks:
                # Ensure that we only have one active deployment task per RampartGraph at a time
                self._deployment_locks[metadata.uid] = asyncio.Lock()

        logger = GraphLogger(LOG, {"metadata": metadata})

        # Fetch the RampartGraph CR object again to make sure we are using the most recent
        # version. Changes to the CR could have occured between when this function was
        # enqueued and now.
        graph_obj = await self._get_graph(metadata)

        is_deletion_task = False
        cur_generation = None
        # Kubernetes denotes that an object is set for deletion by adding a deletionTimestamp
        # field to the metadata. If the graph specification is `deploy: False`, then we also
        # need to undeploy the graph
        if graph_obj is None or "deletionTimestamp" in graph_obj["metadata"] or \
                not graph_obj["spec"].get("deploy", True):
            is_deletion_task = True
        else:
            cur_generation = graph_obj["metadata"]["generation"]

        # The following block of code manages interrupting existing deployment tasks.
        # For example, if the current deployment is stuck, updating/deleting the CR
        # should not be stuck waiting behind the current deployment, and instead should cancel
        # the existing deployment task.
        wait_for_cancellation = False
        if metadata.uid in self._deployment_tasks:
            prev_is_deletion_task, prev_task_generation, task = self._deployment_tasks[metadata.uid]

            if is_deletion_task:
                # Graph is marked for deletion: need to interrupt any existing deployment tasks
                if not prev_is_deletion_task:
                    logger.info(
                        "canceling existing deployment task", extra={"phase": GraphPhase.TEARDOWN})
                    task.cancel()
                else:
                    # The graph is already being deleted. Our work here is done.
                    return
            else:
                # Graph is marked for update: interrupt existing deployments with older generation
                if prev_is_deletion_task:
                    # We do not interrupt deletion tasks. Watch will pick up new update eventually.
                    return
                elif cur_generation > prev_task_generation:
                    # When there is a newer (higher generation) graph obj than the one currently
                    # deploying, cancel the current deployment and deploy the newer graph instead
                    logger.info(
                        f"Found a more recent graph object: generation {cur_generation}, which is "
                        f"greater than the graph being deployed: generation {prev_task_generation}."
                        f" Canceling existing deployment task",
                        extra={"phase": GraphPhase.TEARDOWN})
                    task.cancel()
                    wait_for_cancellation = True
                elif cur_generation == prev_task_generation:
                    # If graph obj is the same as what is being deployed, no need to deploy anything
                    return
                else:
                    logging.error(f"The current deployment has a newer generation "
                                  f"{prev_task_generation} "
                                  f"than the new graph object's {cur_generation}")

        async with self._deployment_locks[metadata.uid]:
            if wait_for_cancellation:
                # task.cancel() was called before. Here we wait for that cancelation to complete
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            # Here we create the deployement task for the CR,
            # store it for later (in case we need to cancel it, etc),
            # and then launch the task
            task = asyncio.create_task(self._sync_graph_task(metadata, logger))
            self._deployment_tasks[metadata.uid] = is_deletion_task, cur_generation, task
            try:
                await task
            except asyncio.CancelledError:
                logging.info(
                    "deployment task was canceled due to graph deletion during deployment",
                    extra={"phase": GraphPhase.DEPLOYMENT})
            del self._deployment_tasks[metadata.uid]

    async def _sync_graph_task(self, metadata, logger):
        """
        This function does the actual work of updating the cluster to reflect the state
        desired by the RampartGraph CR.

        Args:
            metadata (objects.base_type.Metadata): metadata of the RampartGraph CR
            logger (utils.logger.GraphLogger): logger that contains graph-specific formatting
        """
        # Need to get an up-to-date version of the graph in case
        # the graph object has changed since it was added to the queue
        graph_obj = await self._get_graph(metadata)
        if graph_obj is None:  # graph has been fully deleted
            await Graph.teardown(metadata, WORKDIR)
            return

        # deleted is marked for deletion
        if "deletionTimestamp" in graph_obj["metadata"]:
            logger.info("graph marked for deletion", extra={"phase": GraphPhase.TEARDOWN})
            # iff the finalizer exists in the CR, then we haven't completed teardown
            if FINALIZER in graph_obj["metadata"]["finalizers"]:
                # Perform teardown and then patch the CR to remove the finalizer

                # TODO: get component objects without needing to re-pull annotations from helm
                #       and validate
                graph = await Graph.from_json(
                    graph_obj["spec"], metadata, workdir=WORKDIR, validate_specs=False)
                patch_status = {"status": {"phase": "Deleting"}}
                await self._patch_graph_status(metadata.namespace.kubernetes_view,
                                               metadata.name.kubernetes_view,
                                               patch_status)
                try:
                    await graph.validate(validate_specs=False)
                    await graph.teardown_namespaces(list(graph.namespaces))
                except ValidationError:
                    pass
                await Graph.teardown(metadata, WORKDIR)
                graph_obj["metadata"]["finalizers"].remove(FINALIZER)
                try:
                    logger.info(f"removing finalizer from graph: {metadata}",
                                extra={"phase": GraphPhase.TEARDOWN})
                    await self._objs_api.replace_namespaced_custom_object(
                        "rampart.petuum.com", RAMPART_CRD_VERSION,
                        metadata.namespace.kubernetes_view,
                        "rampartgraphs", metadata.name.kubernetes_view, graph_obj)
                except kubernetes.client.rest.ApiException:
                    return None
            return None
        # `status.observedGeneration` is the latest value of `metadata.generation` that we
        # have finished deployment. If `status.observedGeneration` is the same as
        # `metadata.generation` then the current CR has been deployed and we do not need to
        # do anything. Note that "finished" in this context can also mean a deployment failure.
        if ("status" in graph_obj and "observedGeneration" in graph_obj["status"] and
                graph_obj["status"]["observedGeneration"] ==
                graph_obj["metadata"]["generation"]):
            return

        # Use ChainMap to record updates to the job status fields.
        graph_obj["status"] = collections.ChainMap({}, graph_obj.get("status", {}))

        # Controller failure prior to the status patch in the `finally` branch
        # will cause the controller to retry deployment of the graph object when it restarts,
        # as `status.observedGeneration` will not match `metadata.generation`.
        # Idempotency is required.
        try:
            # `Validate` does not alter kubernetes state, so this phase is
            # idempotent w/r to kubernetes. Controller pod redeployment
            # introduces no issues with validation.
            graph = await Graph.from_json(graph_obj["spec"], metadata, workdir=WORKDIR)

            # This validation is mandatory for ensuring pulsar state has not switched
            # between validator and controller and for the chart specs.
            await graph.validate(validate_specs=True)

            # Get a list of infrastructure requirements that this graph provides,
            # and register these. Components that specify those requirements as pre-requisites
            # will be able to be deployed once these requirements are registered.
            provided = graph.provided
            await apply_infra_object(metadata, provided, "registered")

            # attach ownerReferences to the object containing the list of requirements
            # that this graph provides, so that when the graph is destroyed, the list of
            # provided requirements is destroyed as well
            await patch_ownerreference(graph.metadata, graph._owner_reference)
        except ValidationError as e:
            graph_obj["status"]["phase"] = "Failed"
            graph_obj["status"]["reason"] = "GraphValidationError"
            graph_obj["status"]["messages"] = str(e)
            graph_obj["status"]["observedGeneration"] = graph_obj["metadata"]["generation"]
            return
        else:
            try:
                # If the controller terminates during this phase, the kubernetes state may be
                # left in a partial deployment. However, this will also cause the
                # `status.observedGeneration` field to not be updated,
                # so this phase will be retried.
                #
                # It is critical that the `graph.deploy()` implementation must finish the
                # deployment that the previous partial deployment started.
                # Also note that this requirement is generally met by the same functionality
                # required by `graph.deploy()` to handle redeployment with an updated graph object.
                try:
                    # By adding a custom finalizer, deletion of the RampartGraph CR
                    # from here on out will require this controller to manually handle cleanup
                    patch = {"metadata": {"finalizers": [FINALIZER]}}
                    logger.info("adding finalizer", extra={"phase": GraphPhase.VALIDATION})
                    await merge_patch_namespaced_custom_object(
                        self._objs_api, "rampart.petuum.com", RAMPART_CRD_VERSION,
                        metadata.namespace.kubernetes_view,
                        "rampartgraphs", metadata.name.kubernetes_view, patch)

                    if graph.to_deploy:
                        patch_status = {"status": {"phase": "Deploying"}}
                    else:
                        patch_status = {"status": {"phase": "Undeploying"}}
                    await self._patch_graph_status(metadata.namespace.kubernetes_view,
                                                   metadata.name.kubernetes_view,
                                                   patch_status)
                except kubernetes.client.rest.ApiException as exc:
                    if exc.status == 404:
                        return None
                    raise DeploymentError({(
                        f"Deployment failed updating the graph status:\n"
                        f"error code: {exc.status}\n"
                        f"reason:\n{exc.reason}\n\n")})
                else:
                    graph_obj = await self._get_graph(metadata)
                    if graph_obj is None:  # Graph has been deleted in the meantime
                        return
                    graph_obj["status"] = collections.ChainMap({}, graph_obj.get("status", {}))

                if graph.to_deploy:
                    await graph.deploy()
                else:
                    await graph.undeploy()

                # We need to manually clean up the namespaces of components that have been
                # removed from the graph. This is a limitation of helmfile.
                if "componentNamespaces" in graph_obj["status"]:
                    await graph.teardown_old_namespaces(
                        graph_obj["status"]["componentNamespaces"])
                if graph.to_deploy:
                    graph_obj["status"]["phase"] = "Deployed"
                else:
                    graph_obj["status"]["phase"] = "Undeployed"

                # Deployment/Undeployment is functionally complete at this point.
                # From here until the end is just updating the RampartGraph CR to reflect that

                # We need to add all of the ingress and apisix information to the graph status
                # so that they are easily available to users.
                #
                # TODO: Move "endpointPaths" related stuff to another file
                ing_list = (await self._network_api.list_ingress_for_all_namespaces(
                    label_selector=CONTROLLED_BY_RAMPART)).items
                try:
                    ar_list = (await self._objs_api.list_cluster_custom_object(
                        APISIX_ROUTE_API, APISIX_ROUTE_VERSION, APISIX_ROUTE_KIND_PL,
                        label_selector=CONTROLLED_BY_RAMPART)).get("items", [])
                except kubernetes.client.rest.ApiException as exc:
                    # 404 is raised when ApisixRoute CRD is not installed on the cluster.
                    # This can be handled by assigning [] to ar_list.
                    if exc.status == 404:
                        ar_list = []
                    else:
                        raise exc
                ns_to_comp = graph.namespace_to_component_map
                comp_to_paths = {}
                for ing in ing_list:
                    if ing.metadata.namespace in ns_to_comp:
                        comp_name = ns_to_comp[ing.metadata.namespace]
                        ing_paths = sum((rule.http.paths for rule in ing.spec.rules), [])
                        ing_paths = [path.path for path in ing_paths]
                        comp_to_paths[comp_name] = comp_to_paths.get(comp_name, set())
                        comp_to_paths[comp_name].update(ing_paths)
                for ar in ar_list:
                    namespace = ar.get("metadata", {}).get("namespace", None)
                    if namespace is not None and namespace in ns_to_comp:
                        comp_name = ns_to_comp[namespace]
                        ar_paths = sum((http.get("match", {}).get("paths", [])
                                        for http in ar.get("spec", {}).get("http", [])), [])
                        ar_paths = [path.strip("*") for path in ar_paths]
                        comp_to_paths[comp_name] = comp_to_paths.get(comp_name, set())
                        comp_to_paths[comp_name].update(ar_paths)
                for key, val in comp_to_paths.items():
                    comp_to_paths[key] = list(val)

                graph_obj["status"]["endpointPaths"] = json.dumps(comp_to_paths)
                graph_obj["status"]["componentNamespaces"] = graph.namespaces

                # This last `observedGeneration` value lets the controller know that it doesn't
                # need to redeploy this version of the RampartGraph CR
                graph_obj["status"]["observedGeneration"] = graph_obj["metadata"]["generation"]
            except DeploymentError as e:
                logger.error(e, exc_info=True, extra={"phase": GraphPhase.DEPLOYMENT})
                graph_obj["status"]["phase"] = "Failed"
                graph_obj["status"]["reason"] = "GraphDeploymentError"
                graph_obj["status"]["messages"] = str(e)
                graph_obj["status"]["observedGeneration"] = graph_obj["metadata"]["generation"]
            except Exception as e:
                logger.error(e, exc_info=True, extra={"phase": GraphPhase.DEPLOYMENT})
        finally:
            # If the controller terminates during this phase, then `graph.deploy()` on
            # the most recent version of this graph object will be retried. Therefore,
            # `graph.deploy()` must implement redeployment when applied to an updated
            # graph object and must be idempotent when applied to the same graph object
            patch = {"status": {k: v for k, v in graph_obj["status"].maps[0].items()
                                if v != graph_obj["status"].maps[1].get(k)}}
            if patch["status"]:
                try:
                    return await self._patch_graph_status(metadata.namespace.kubernetes_view,
                                                          metadata.name.kubernetes_view,
                                                          patch)
                except kubernetes.client.rest.ApiException as exc:
                    if exc.status != 404:
                        raise

    async def _get_graph(self, metadata):
        """Return the RampartGraph CR object for the given metadata."""
        try:
            graph = await self._objs_api.get_namespaced_custom_object(
                "rampart.petuum.com", RAMPART_CRD_VERSION, metadata.namespace.kubernetes_view,
                "rampartgraphs", metadata.name.kubernetes_view)
        except kubernetes.client.rest.ApiException as exc:
            if exc.status == 404:
                return None
            raise  # Unexpected error.
        if graph["metadata"]["uid"] != metadata.uid:
            return None
        return graph


if __name__ == "__main__":
    # This following line requires the controller to be running from within a kubernetes cluster.
    kubernetes.config.load_incluster_config()
    controller = RampartController()
    loop = asyncio.get_event_loop()
    loop.run_until_complete(
        controller.run(),
    )
    loop.close()
