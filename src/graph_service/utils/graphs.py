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

import asyncio
import yaml
import logging
from asyncio.subprocess import create_subprocess_exec, PIPE
from tinydb import TinyDB, Query
from datetime import datetime, timezone, timedelta

import kubernetes_asyncio as kubernetes
from grafana_dashboard.service import delete_dashboard
from .constants import TIMEOUT, LOGGING_FORMAT, COMPONENT_STATE_MAP, STATE_MAP
from .utils import filter_metadata, dict_hash, app_id_from_metadata
from .grafana import create_or_modify_grafana_dashboard

graph_versions_db = TinyDB('/etc/graphs/versions.json')
app_db = TinyDB('/etc/graphs/apps.json')
dashboard_db = TinyDB('/etc/graphs/dashboard.json')

kubernetes.config.load_incluster_config()
objs_api = kubernetes.client.CustomObjectsApi()
core_api = kubernetes.client.CoreV1Api()

lock = asyncio.Lock()

logging.basicConfig(format=LOGGING_FORMAT)
LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)


async def get_helm_status(component_ns, helm_release_name="component"):
    proc = await create_subprocess_exec(
        "helm", "list", "-n", component_ns, "-o", "yaml",
        stdout=PIPE, stderr=PIPE)
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=TIMEOUT)
    if proc.returncode:
        raise RuntimeError(f'Unexpected error, "helm list -n {component_ns} -o yaml" returned'
                           f' error code {proc.returncode} with message {stderr.decode}')
    deployments = yaml.safe_load(stdout.decode())
    if component_ns not in set(deployment["namespace"] for deployment in deployments):
        return "Not Found", ""

    proc = await create_subprocess_exec(
        "helm", "status", "-n", component_ns, helm_release_name, "-o", "yaml",
        stdout=PIPE, stderr=PIPE)
    stdout, stderr = await asyncio.wait_for(proc.communicate(), TIMEOUT)
    deployment = yaml.safe_load(stdout.decode())
    if (not deployment) or ("info" not in deployment) or ("status" not in deployment["info"]):
        status = "Unknown"
        description = "status not found"
    else:
        status = deployment["info"]["status"]
        description = deployment["info"]["description"]

    if status == "deployed":
        return "normal", description
    elif status == "pending-install":
        return "installing", description
    else:
        return "error", description


async def get_metadata_from_app_id(app_id):
    async with lock:
        app_query = Query()
        metadata_list = app_db.search(app_query.app_id == app_id)
        if not metadata_list:
            raise KeyError()
        else:
            assert (len(metadata_list) == 1), f"Found more than one graph for app_id {app_id}"
            metadata = metadata_list[0]
            return metadata["namespace"], metadata["name"], metadata


async def get_component_status(component_ns):
    try:
        helm_status, component_message = await get_helm_status(component_ns)
    except RuntimeError:
        LOG.error(f"Cannot connect to component: {component_ns}")
        component_message = f"Cannot connect to component: {component_ns}"
        helm_status = "error"
    if helm_status == "Not Found":
        component_status = COMPONENT_STATE_MAP["NotFound"]
    elif helm_status == "error":
        component_status = COMPONENT_STATE_MAP["Failed"]
    elif helm_status == "installing":
        component_status = COMPONENT_STATE_MAP["Installing"]
    else:
        component_status = COMPONENT_STATE_MAP["Normal"]
        try:
            pod_list = await core_api.list_namespaced_pod(component_ns)
        except kubernetes.client.rest.ApiException as e:
            LOG.error(f"Cannot list namespaced pod: {component_ns} due to {e.reason}")
            component_message = f"Cannot list namespaced pod: {component_ns} due to {e.reason}"
            component_status = COMPONENT_STATE_MAP["Failed"]
            return component_status, component_message
        # TODO: make the timeout customizable on rampart UI
        status_timeout = timedelta(seconds=600)
        # TODO: catch if a pod is not allocatable (stuck in pending) due to resource constraints
        pods = (p for p in pod_list.items if p.status.container_statuses is not None)
        for pod in pods:
            waiting_container_statuses = (cs for cs in pod.status.container_statuses if cs.ready is
                                          False and cs.state.waiting is not None)
            for container_status in waiting_container_statuses:
                waiting_state = container_status.state.waiting
                if waiting_state.reason is not None:
                    LOG.error(f"The pod {pod.metadata.name} of namespace {pod.metadata.namespace} "
                              f"is in {waiting_state.reason}")
                    component_message = f"The pod {pod.metadata.name} of namespace " \
                                        f"{pod.metadata.namespace} is in {waiting_state.reason}"

                    is_timeout = (datetime.now(timezone.utc).astimezone() -
                                  pod.metadata.creation_timestamp) > status_timeout
                    if is_timeout:
                        component_status = COMPONENT_STATE_MAP["DeployedWithPersistentErrors"]
                    else:
                        component_status = COMPONENT_STATE_MAP["DeployedWithTransientErrors"]
                    return component_status, component_message

    return component_status, component_message


async def get_volume_flows_status(flow_ns):
    try:
        helm_status, volume_flows_msg = await get_helm_status(flow_ns, "flows-volume")
    except RuntimeError:
        LOG.error(f"Cannot connect to component: {flow_ns}")
        volume_flows_msg = f"Cannot connect to component: {flow_ns}"
        helm_status = "error"
    if helm_status == "Not Found":
        volume_flows_status = COMPONENT_STATE_MAP["NotFound"]
    elif helm_status == "error":
        volume_flows_status = COMPONENT_STATE_MAP["Failed"]
    elif helm_status == "installing":
        volume_flows_status = COMPONENT_STATE_MAP["Installing"]
    else:
        volume_flows_status = COMPONENT_STATE_MAP["Normal"]

    return volume_flows_status, volume_flows_msg


async def get_app_status(namespace, name):
    try:
        graph_obj = await objs_api.get_namespaced_custom_object(
            "rampart.petuum.com", "v1beta2", namespace, "rampartgraphs", name)
    except kubernetes.client.rest.ApiException as exc:
        if exc.status == 404:
            return STATE_MAP["Undeployed"]
        else:
            return STATE_MAP["Failed"]

    status_obj = graph_obj.get("status", {})
    graph_phase = status_obj.get("phase", None)
    if graph_phase != "Deployed":
        return STATE_MAP[graph_phase]

    spec_obj = graph_obj["spec"]
    metadata_obj = graph_obj["metadata"]
    for component, obj in spec_obj["graph"]["components"].items():
        component = component.replace('_', '-')
        if "namespace" not in obj:
            component_ns = "-".join([
                metadata_obj["namespace"], metadata_obj["name"],
                component])
        else:
            component_ns = obj["namespace"]

        component_status, _ = await get_component_status(component_ns)
        if component_status != COMPONENT_STATE_MAP["Normal"]:
            return STATE_MAP["DeployedWithErrors"]
    return STATE_MAP[graph_phase]


async def sync_graph(name, namespace):
    try:
        graph_query = Query()
        graph_versions = graph_versions_db.search((graph_query.namespace == namespace)
                                                  & (graph_query.name == name))
        new_version = len(graph_versions) + 1  # 1-indexed
        graph_obj = await objs_api.get_namespaced_custom_object(
            "rampart.petuum.com", "v1beta2", namespace, "rampartgraphs", name)
    except kubernetes.client.rest.ApiException as exc:
        if exc.status != 404:
            LOG.error(exc, exc_info=True)
        elif len(graph_versions) > 0:
            # Do not delete/modify records from DB until the CR is deleted from the K8s
            app_query = Query()
            metadata_list = app_db.search((app_query.namespace == namespace) &
                                          (app_query.name == name))
            if len(metadata_list) > 0:
                graph_query = Query()
                graph_versions_db.remove((graph_query.namespace == namespace) &
                                         (graph_query.name == name))
                app_db.remove((app_query.namespace == namespace) &
                              (app_query.name == name))

                dashboard_query = Query()
                app_id = app_id_from_metadata({"namespace": namespace, "name": name})
                dashboards = dashboard_db.search((dashboard_query.app_id == app_id))
                LOG.info(f"found dashboards to delete: {dashboards}")
                for dashboard in dashboards:
                    await delete_dashboard(dashboard["dashboard_uid"])
                dashboard_db.remove((dashboard_query.app_id == app_id))
        return
    async with lock:
        if len(graph_versions) > 0:
            previous_uid = graph_versions[-1]['graph']["uid"]
        else:
            previous_uid = "not_found"

        uid = graph_obj["metadata"]["uid"]
        app_id = app_id_from_metadata(graph_obj["metadata"])
        timestamp = datetime.now(timezone.utc).astimezone().isoformat()

        hash_value = dict_hash(graph_obj["spec"]["graph"])

        matches = [
            (hash_value == previous_version["hash"], previous_version["version"],
             previous_version["status"])
            for previous_version in graph_versions]
        for match, old_version, old_status in matches:
            if match:
                version = old_version
                status = old_status
                break
        else:
            version = new_version
            status = None

        app_query = Query()
        active = graph_obj["spec"].get("deploy", True)
        if previous_uid != graph_obj["metadata"]["uid"]:
            app_db.upsert({
                "uid": uid,
                "app_id": app_id,
                "namespace": graph_obj["metadata"]["namespace"],
                "name": graph_obj["metadata"]["name"],
                "desc": "",
                "active":  str(active),
                "labels": graph_obj["metadata"].get("labels", None),
                "graph": filter_metadata(graph_obj),
                "activeVersion": version,
                "versionCount": len(graph_versions)},
                (app_query.namespace == namespace) & (app_query.name == name))
        else:
            uid = previous_uid
            app_db.update({
                "labels": graph_obj["metadata"].get("labels", None),
                "graph": filter_metadata(graph_obj),
                "activeVersion": version,
                "versionCount": len(graph_versions)},
                (app_query.uid == uid) & (app_query.app_id == app_id))

        # Set the previous graphs to disabled
        graph_versions_db.update(
            {"active": "False"},
            (graph_query.namespace == namespace)
            & (graph_query.name == name)
            & (graph_query.active == "True"))

        graph_versions_db.upsert({
                            "namespace": namespace,
                            "name": name,
                            "version": version,
                            "hash": hash_value,
                            "status": status,
                            "active": str(active),
                            "graph": {
                                        "object": filter_metadata(graph_obj),
                                        "timestamp": timestamp,
                                        "uid": uid}
                        },
                        (graph_query.namespace == namespace)
                        & (graph_query.name == name)
                        & (graph_query.version == version))

        # Update the lastDeploymentTimestamp with the lastModified timestamp from the status field
        if graph_obj.get('status', {}).get('phase') == "Deploying":
            graph_versions_db.update({"lastDeploymentTimestamp": graph_obj.get("status", {}).get(
                "lastModified", timestamp)},
                (graph_query.namespace == namespace)
                & (graph_query.name == name)
                & (graph_query.version == version))
            app_db.update({"lastDeploymentTimestamp": graph_obj.get("status", {}).get(
                "lastModified", timestamp)},
                (graph_query.namespace == namespace)
                & (graph_query.name == name))

        # Set default creationTimestamp for graph_version_db items in case the value doesn't exist
        graph_version = graph_versions_db.search((graph_query.namespace == namespace)
                                                 & (graph_query.name == name)
                                                 & (graph_query.version == version))[0]
        if "creationTimestamp" not in graph_version:
            graph_versions_db.update({"creationTimestamp": graph_obj.get("metadata", {}).get(
                "creationTimestamp", timestamp)},
                (graph_query.namespace == namespace)
                & (graph_query.name == name)
                & (graph_query.version == version))

        # Set default lastEditTimestamp for app_db items in case the value doesn't exist
        metadata_from_db = app_db.search((app_query.namespace == namespace)
                                         & (app_query.name == name))[0]
        if "lastEditTimestamp" not in metadata_from_db:
            app_db.update({"lastEditTimestamp": graph_obj.get("metadata", {}).get(
                "creationTimestamp", timestamp)},
                (graph_query.namespace == namespace)
                & (graph_query.name == name))

        # Clear the status of the previous graphs
        if ("status" in graph_obj) and ("phase" in graph_obj["status"])\
                and (graph_obj["status"]["phase"] == "Deployed"):
            graph_versions_db.update(
                {"status": None},
                (graph_query.namespace == namespace)
                & (graph_query.name == name)
                & (graph_query.status == "Undeploying"))

        status = graph_obj.get("status", {})
        generation = status.get("observedGeneration", 0)
        namespaces = status.get("componentNamespaces", [])
        await create_or_modify_grafana_dashboard(
            namespace, name, app_id_from_metadata(graph_obj["metadata"]), generation,
            namespaces)


async def watch_graphs_task():
    async with kubernetes.watch.Watch() as watch:
        while True:
            try:
                async for event in watch.stream(
                        objs_api.list_namespaced_custom_object,
                        "rampart.petuum.com", "v1beta2", "", "rampartgraphs", timeout_seconds=60):
                    graph_name = event["object"]["metadata"]["name"]
                    namespace = event["object"]["metadata"]["namespace"]
                    LOG.info(f"Found event: {namespace}/{graph_name}")
                    asyncio.create_task(sync_graph(graph_name, namespace))
            except asyncio.TimeoutError:
                LOG.error("Catch TimeoutError, Sleep 60s")
                await asyncio.sleep(60)
            except Exception as e:
                LOG.error(f"Catch Exception: {str(e)}, Sleep 60s")
                await asyncio.sleep(60)
