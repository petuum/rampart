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

import kubernetes_asyncio as kubernetes

import logging

from .deployment import required_deploy
from ..constants import LOGGING_FORMAT, RAMPART_INFRA_K8S_KEY_GEN
from ..k8s_templates.infra import infra_template
from ..repository import get_global_repo_manager
from ..utils.deployment import merge_patch_namespaced_custom_object,\
    merge_patch_namespaced_custom_object_status
from ..utils.logger import GraphLogger


kubernetes.config.load_incluster_config()
objs_api = kubernetes.client.CustomObjectsApi()

logging.basicConfig(format=LOGGING_FORMAT)
LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)


async def apply_infra_object(metadata, provided, status_phase):
    """
    Creates or updates a unique kubernetes custom resource object to indicate what
    infrastructure is provided by the graph

    Args:
        metadata (base_types.Metadata): metadata for the graph
        provided (list): list of strings denoting what the graph provides
        status_phase ("registered" | "deployed"):
            "registered" indicates that we know that the graph provides `provided` to
            prevent the same infrastructure from multiple graphs from colliding.
            "deployed" indicates that the infrastructure is ready
    """
    logger = GraphLogger(LOG, {"metadata": metadata})
    k8s_key = RAMPART_INFRA_K8S_KEY_GEN(metadata.namespace.kubernetes_view)

    if status_phase == "registered":
        phase = "Validation"
    elif status_phase == "deployed":
        phase = "Deployment"
    try:
        infra_obj = await objs_api.get_namespaced_custom_object(
            *k8s_key, metadata.name.kubernetes_view)
        logger.info(f"found infra object: {metadata.name.kubernetes_view}", extra={"phase": phase})
    except kubernetes.client.rest.ApiException as exc:
        if exc.status == 404:
            logger.info(f"creating new infra object: {metadata.name.kubernetes_view}",
                        extra={"phase": phase})
            infra_obj = infra_template(metadata.name.kubernetes_view,
                                       metadata.namespace.kubernetes_view, provided)
            await objs_api.create_namespaced_custom_object(
                *k8s_key, infra_obj)
    else:
        change = {"spec": {"provides": [{"name": infra} for infra in provided]}}
        logger.info(f"updating infra object: {metadata.name.kubernetes_view}",
                    extra={"phase": phase})
        await merge_patch_namespaced_custom_object(
            objs_api, *k8s_key, metadata.name.kubernetes_view, change)

    status = infra_obj.get("status", {"provides": []})
    source = {"namespace": metadata.namespace.kubernetes_view,
              "name": metadata.name.kubernetes_view}
    status["provides"] = [{"name": infra, "status": status_phase, "source": source}
                          for infra in provided]
    await merge_patch_namespaced_custom_object_status(
        objs_api, *k8s_key, metadata.name.kubernetes_view, {"status": status})


# TODO: merge with apply_infra_object
async def patch_ownerreference(metadata, owner_reference):
    """adds ownerreference to the k8s object from `apply_infra_object"""
    k8s_key = RAMPART_INFRA_K8S_KEY_GEN(metadata.namespace.kubernetes_view)
    infra_obj = {"metadata": {"ownerReferences": owner_reference}}

    await required_deploy(
        merge_patch_namespaced_custom_object,
        objs_api, *k8s_key, metadata.name.kubernetes_view, infra_obj)


def pulsar_enabled():
    """return true iff there is a graph that provides pulsar"""
    return "pulsar" in get_global_repo_manager().provided
