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

from ..objects.base_types import Metadata, KubernetesName
from ..k8s_templates.name_decorator import use_kubernetes_name
import aiohttp
import asyncio
import copy
import inspect
import time
import kubernetes_asyncio as kubernetes
import logging
import subprocess

from .classes import DeploymentError, GraphPhase
from .logger import GraphLogger
from ..constants import HNS_API, HNS_VERSION, HNS_KIND_PL, HNS_TEMPLATE, LOGGING_FORMAT, \
    NS_TERMINATION_TIMEOUT

logging.basicConfig(format=LOGGING_FORMAT)
LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)


kubernetes.config.load_incluster_config()
crd_api = kubernetes.client.ApiextensionsV1Api()


def require_validated(func):
    """
    Decorator that requires the instance object of the applied function to have
    `validated` set to `True`.

    Apply to functions that require the object to be validated.
    """
    def wrapper(obj, *args, **kwargs):
        if not obj.validated:
            raise TypeError(f"Cannot deploy an unvalidated {type(obj)}: {obj.name}")
        else:
            return func(obj, *args, **kwargs)
    return wrapper


# TODO: Wrap the errors from these functions in DeploymentError instances
async def required_deploy(func, *args, **kwargs):
    """
    Call `func` with the applied args and require it to not raise an error.
    Use for deployment. Returns the result from `func`.
    """
    try:
        return await func(*args, **kwargs)
    except Exception as e:
        raise e


async def optional_deploy(func, predicate=None, *args, **kwargs):
    """
    Call `func` with the applied args and allow it to fail if the
    `predicate` function is true when applied to the exception to be raised.
    Use for deployment. Returns the result from `func`.
    """
    try:
        return await func(*args, **kwargs)
    except Exception as e:
        if predicate and not predicate(e):
            raise e
        else:
            return e


async def required_teardown(func, *args, **kwargs):
    """
    Call `func` with the applied args and require it to not raise an error.
    Use for teardown. Does not return anything.
    """
    try:
        await func(*args, **kwargs)
    except Exception as e:
        raise e


async def optional_teardown(func, predicate=None, *args, **kwargs):
    """
    Call `func` with the applied args and allow it to fail if the
    `predicate` function is true when applied to the exception to be raised
    Use for teardown. Does not return anything.
    """
    try:
        await func(*args, **kwargs)
    except Exception as e:
        if predicate and not predicate(e):
            raise e
        else:
            return e
    return None


async def subprocess_with_return_code(graph_metadata, return_codes, interrupt_on_cancel,
                                      callback_on_cancel, *args, **kwargs):
    """
    Creates a subprocess with `*args, **kwargs`.

    Args:
        graph_metadata (base_types.Metadata): Metadata of the graph this is called for.
                                              Used for logging.
        return_codes (List | Set | Dict): Some set of allowable return codes.
                                          Will raise an exception if the subprocess's return code
                                          is not one of these.
        interrupt_on_cancel (bool): Interrupt the subprocess if the parent task is canceled.
                                    Use for deployment tasks that can take a long time.
                                    Note: You may need to clean up partial deployment after
                                    this subprocess is canceled.
        callback_on_cancel (function | None): Callback ran when cancelled. Not ran if `None`.
                                              Use this to clean up partial deployment
        *args: actual arguments of the subprocess to run. The first element is the command to run
               See https://docs.python.org/3/library/asyncio-subprocess.html#asyncio.create_subprocess_exec # noqa E501
        **kwargs: kwargs passed in to asyncio.create_subprocess_exec

    returns:
        return code, stdout, stderr of subprocess if the return code is in `return_codes`
        raises a `DeploymentError` otherwise
    """

    if not graph_metadata:
        logger = GraphLogger(LOG, {"metadata": None})
    else:
        logger = GraphLogger(LOG, {"metadata": graph_metadata})

    for key, value in [("stdout", subprocess.PIPE), ("stderr", subprocess.PIPE)]:
        if key not in kwargs:
            kwargs[key] = value

    try:
        started = False
        proc = await asyncio.create_subprocess_exec(*args, **kwargs)

        started = True
        await proc.wait()
    except asyncio.CancelledError:
        if interrupt_on_cancel and started:
            proc.terminate()
            await proc.wait()

        if inspect.iscoroutinefunction(callback_on_cancel):
            await callback_on_cancel()
        elif callable(callback_on_cancel):
            callback_on_cancel()
        raise asyncio.CancelledError

    stdout = (await proc.stdout.read()).decode("utf-8")
    stderr = (await proc.stderr.read()).decode("utf-8")
    if proc.returncode not in return_codes:
        logger.info(stdout)
        logger.error(stderr)
        raise DeploymentError({(
            f"Deployment failed running {args, kwargs}: error code {proc.returncode}\n"
            f"stdout:\n{stdout}\n\n"
            f"stderr:\n{stderr}")})
    return proc.returncode, stdout, stderr


async def required_subprocess(graph_metadata, interrupt_on_cancel,
                              callback_on_cancel, *args, **kwargs):
    """
    Creates a subprocess with `*args, **kwargs`, requiring it to succeed.

    Args:
        graph_metadata (base_types.Metadata): Metadata of the graph this is called for.
                                              Used for logging.
        interrupt_on_cancel (bool): Interrupt the subprocess if the parent task is canceled.
                                    Use for deployment tasks that can take a long time.
                                    Note: You may need to clean up partial deployment after
                                    this subprocess is canceled.
        callback_on_cancel (function | None): Callback ran when cancelled. Not ran if `None`.
                                              Use this to clean up partial deployment
        *args: actual arguments of the subprocess to run. The first element is the command to run
               See https://docs.python.org/3/library/asyncio-subprocess.html#asyncio.create_subprocess_exec # noqa E501
        **kwargs: kwargs passed in to asyncio.create_subprocess_exec

    returns:
        stdout, stderr of subprocess if the return code is 0
        raises a `DeploymentError` otherwise
    """
    return await subprocess_with_return_code(
        graph_metadata, [0], interrupt_on_cancel, callback_on_cancel, *args, **kwargs)


async def optional_subprocess(graph_metadata, interrupt_on_cancel,
                              callback_on_cancel, *args, **kwargs):
    """
    Creates a subprocess with `*args, **kwargs`, allowing it to fail.

    Args:
        graph_metadata (base_types.Metadata): Metadata of the graph this is called for.
                                              Used for logging.
        interrupt_on_cancel (bool): Interrupt the subprocess if the parent task is canceled.
                                    Use for deployment tasks that can take a long time.
                                    Note: You may need to clean up partial deployment after
                                    this subprocess is canceled.
        callback_on_cancel (function | None): Callback ran when cancelled. Not ran if `None`.
                                              Use this to clean up partial deployment
        *args: actual arguments of the subprocess to run. The first element is the command to run
               See https://docs.python.org/3/library/asyncio-subprocess.html#asyncio.create_subprocess_exec # noqa E501
        **kwargs: kwargs passed in to asyncio.create_subprocess_exec

    returns:
        stdout, stderr of subprocess if no `DeploymentError` was raised
        The `DeploymentError` instance of `DeploymentError` was raised
        Note: `DeploymentError` will be raised if the return code is not 0
    """
    try:
        return_code, stdout, stderr = await required_subprocess(
            graph_metadata, interrupt_on_cancel, callback_on_cancel, *args, **kwargs)
    except DeploymentError as e:
        return e
    return stdout, stderr


@use_kubernetes_name
async def deploy_sub_namespace(name, parent_name, owner_reference,
                               custom_api, core_api, graph_metadata=None):
    """
    Deploys a subnamespace.
    See https://kubernetes.io/blog/2020/08/14/introducing-hierarchical-namespaces/

    Args:
        name (str): Name of the namespace to deploy
        parent_name (str): Name of the namespace to make this a subnamespace of
        owner_reference (result from k8s_templates.owner_reference.owner_reference_template):
            owner_reference to attach to the subnamespace anchor
        custom_api: kubernetes.client.CustomObjectsApi instance to use
        core_api: kubernetes.client.CoreV1Api instance to use
        graph_metadata (base_types.Metadata): used for logging
    """
    logger = GraphLogger(LOG, {"metadata": graph_metadata, "phase": "Deployment"})
    hns_body = copy.deepcopy(HNS_TEMPLATE)
    hns_body["metadata"]["namespace"] = parent_name
    hns_body["metadata"]["name"] = name
    hns_body["metadata"]["labels"] = {"controlled-by-rampart": "true"}
    if owner_reference:
        hns_body["metadata"]["ownerReferences"] = owner_reference

    # If the namespace is still terminating, wait for it to finish before deploying
    try:
        ns_resp = await core_api.read_namespace(name)
        phase = ns_resp.status.phase

        start = time.time()
        while phase == 'Terminating':
            ns_resp = await core_api.read_namespace(name)
            phase = ns_resp.status.phase
            await asyncio.sleep(1)

            if time.time() - start > NS_TERMINATION_TIMEOUT:
                logger.error(f"Terminating namespace {name} has exceeded timeout."
                             f"There may be something out of rampart's control blocking "
                             f"its termination, like a finalizer.")
                raise DeploymentError({f"Timed out waiting for namespace {name} to terminate."})
    except kubernetes.client.rest.ApiException as e:
        # If the namespace does not exist, we can continue with its creation
        if e.status != 404:
            raise e

    # This deployment must be optional in case the namespace object already exists,
    # either for graph update or retrying a partial deployment
    logger.info(f"deploying subnamespace {parent_name}/{name}",
                extra={"phase": GraphPhase.DEPLOYMENT})
    try:
        await crd_api.read_custom_resource_definition("subnamespaceanchors.hnc.x-k8s.io")
    except aiohttp.client_exceptions.InvalidURL:
        raise DeploymentError({
            "Cannot get subnamespaceanchor kind. Please ensure that it exists."})
    except kubernetes.client.rest.ApiException:
        raise DeploymentError({
            "Cannot get subnamespaceanchor kind. Please ensure that it exists."})

    try:
        await optional_deploy(custom_api.create_namespaced_custom_object,
                              lambda e: (type(e) == kubernetes.client.rest.ApiException
                                         and e.reason == "Conflict"),
                              HNS_API, HNS_VERSION, parent_name, HNS_KIND_PL, hns_body)
    except kubernetes.client.rest.ApiException as e:
        raise DeploymentError({f"Cannot create subnamespace: {str(e.body)}"})
    async with kubernetes.watch.Watch() as watch:
        # The created namespace needs the label `controlled-by-rampart` for
        # the pod-preset mutation hook to modify the pods for this namespace.
        # Because we did not create the namespace directly, we need to patch
        # it in manually.
        # We also need to allow for cascading deletions in the hierarchy object,
        # so that we can delete this namespace and have its children also deleted.
        # Note: these patches must be idempotent in case of redeployment
        namespace_uid = ""
        patched = False
        while not patched:
            async for event in watch.stream(core_api.list_namespace, timeout_seconds=10):
                if event["object"].metadata.name == name:
                    await asyncio.sleep(1)
                    ns_obj = await core_api.read_namespace(name)
                    namespace_uid = ns_obj.metadata.uid
                    if ns_obj.metadata.labels is not None:
                        ns_obj.metadata.labels["controlled-by-rampart"] = "true"
                    else:
                        ns_obj.metadata.labels = {"controlled-by-rampart": "true"}
                    if (ns_obj.metadata.annotations is None
                            or ns_obj.metadata.annotations.get("hnc.x-k8s.io/subnamespace-of")
                            != parent_name):
                        raise DeploymentError({f"Namespace '{name}' already exists "
                                               f"and is not created by Rampart."})
                    try:
                        await core_api.replace_namespace(name=name, body=ns_obj)
                        patched = True
                        break
                    except kubernetes.client.rest.ApiException as e:
                        if e.reason == "Conflict":
                            logging.warning(
                                f"Failed to update namespace {name} due to conflict. Retrying.")
                        else:
                            raise e

        patched = False
        while not patched:
            async for event in watch.stream(
                    custom_api.list_namespaced_custom_object,
                    group=HNS_API, version=HNS_VERSION,
                    namespace=name, plural="hierarchyconfigurations",
                    timeout_seconds=10):
                hierarchy_obj = {"spec": {"allowCascadingDeletion": True}}
                try:
                    await required_deploy(
                        merge_patch_namespaced_custom_object,
                        custom_api, group=HNS_API, version=HNS_VERSION, namespace=name,
                        plural="hierarchyconfigurations", name="hierarchy",
                        body=hierarchy_obj)
                    patched = True
                except kubernetes.client.rest.ApiException as e:
                    if e.status == 409:
                        pass
                    else:
                        raise
                break
    return Metadata(parent_name, name, namespace_uid)


async def patch_pv(namespace, pvc_names, core_api, owner_reference, pvc_to_flow=None):
    """Patch PV's for both component and flow.
    Reclaim policy for a component's pv is always "Retain", so ownerreferences needs to be set
    to garbage collect the pv.
    Reclaim policy for a flow's pv is determined by the flow's reclaim policy. Additionally,
    ownerreference needs to be set in case of "Retain" to garbage collect the pv.
    This function is idempotent because it overrides pv values based on current graph

    Args:
        namespace (str): namespace of PVC's. Generally the namespace of a component
        pvc_names (list): list of PVC's for which we want to patch their PVs
        core_api: kubernetes.client.CoreV1Api instance to use
        owner_reference (result from k8s_templates.owner_reference.owner_reference_template):
            owner_reference to attach to the PV's. Used to make the PV's die when their PVC's
            are deleted.
        pvc_to_flow (dict): map of pvc_name to flow to give the persistent volume
                            the proper reclaim policy (e.g. not deleting the underlying data
                            when "Retain" is set
    """
    namespace = KubernetesName(namespace)
    async with kubernetes.watch.Watch() as watch:
        patched_pv = set()
        while not len(patched_pv) == len(pvc_names):
            async for event in watch.stream(
                    core_api.list_namespaced_persistent_volume_claim, timeout_seconds=10,
                    namespace=namespace.kubernetes_view):
                pvc = event["object"]
                pvc_name = pvc.metadata.name
                if pvc_name in patched_pv or pvc_name not in pvc_names \
                        or not pvc.spec.volume_name:
                    continue
                pv_patch = kubernetes.client.V1PersistentVolume(
                    metadata=kubernetes.client.V1ObjectMeta(),
                    spec=kubernetes.client.V1PersistentVolumeSpec()
                )
                if pvc_to_flow is not None and pvc_name in pvc_to_flow:
                    flow = pvc_to_flow[pvc_name]
                    pv_patch.spec.persistent_volume_reclaim_policy = flow.reclaim_policy
                else:
                    pv_patch.spec.persistent_volume_reclaim_policy = "Retain"
                # "Retained" pv's need to be garbage collected because the provisioner we are
                # using right now does not seem to care about reusing released pv's at all.
                if pv_patch.spec.persistent_volume_reclaim_policy == "Retain":
                    pv_patch.metadata.owner_references = owner_reference
                try:
                    await core_api.patch_persistent_volume(pvc.spec.volume_name, pv_patch)
                    patched_pv.add(pvc_name)
                except kubernetes.client.rest.ApiException as e:
                    if e.reason == "Conflict":
                        logging.warning(
                            f"Failed to update pv {pvc.spec.volume_name} due to conflict. "
                            "Retrying.")
                    else:
                        raise e


async def merge_patch_namespaced_custom_object(custom_object_api, *args, **kwargs):
    # https://github.com/tomplus/kubernetes_asyncio/issues/68
    kwargs["_content_type"] = "application/merge-patch+json"
    return await custom_object_api.patch_namespaced_custom_object(*args, **kwargs)


async def merge_patch_namespaced_custom_object_status(custom_object_api, *args, **kwargs):
    # https://github.com/tomplus/kubernetes_asyncio/issues/68
    kwargs["_content_type"] = "application/merge-patch+json"
    return await custom_object_api.patch_namespaced_custom_object_status(*args, **kwargs)
