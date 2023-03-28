# Copyright 2023 Petuum, Inc. All Rights Reserved.

import asyncio
import json
import os

import logging


from datetime import datetime, timezone

from fastapi import FastAPI, Response
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware

import kubernetes_asyncio as kubernetes

from operator import itemgetter
from tinydb import TinyDB, Query

import httpx
import pulsar


from utils.constants import K8S_DASHBOARD, PULSAR_CLIENT_SERVICE, STATE_MAP, DEPLOYED_STATES_LIST, \
    COMPONENT_LINKS_TO_DASHBOARD, LOGGING_FORMAT

from utils.utils import filter_metadata, dict_hash, app_id_from_metadata, get_latest_version, \
    is_readonly_app, generate_uuid_str, request

from utils.classes import RedeployModel, GraphModel, NodeConfigsModel

from utils.flows import get_flows_service_url

from utils.graphs import get_component_status, get_volume_flows_status, get_app_status, \
    watch_graphs_task, get_metadata_from_app_id

graph_versions_db = TinyDB('/etc/graphs/versions.json')
app_db = TinyDB('/etc/graphs/apps.json')
dashboard_db = TinyDB('/etc/graphs/dashboard.json')
configs_db = TinyDB('/etc/graphs/configs.json')

app = FastAPI()
app.router.redirect_slashes = False
prefix = os.environ.get("BASE_PATH", "")
if prefix and not prefix.startswith("/"):
    prefix = "/" + prefix

status_endpoint = prefix + "/api/v1/graph-status/{app_id}"
version_endpoint = prefix + "/api/v1/apps/{app_id}/versions/{version}/graph"
graph_endpoint = prefix + "/api/v1/graphs"
app_endpoint = prefix + "/api/v1/apps"
single_app_endpoint = prefix + "/api/v1/apps/{app_id}"
patch_graph_endpoint = prefix + "/api/v1/apps/{app_id}/graph"
redeployment_endpoint = prefix + "/api/v1/apps/redeployment/{app_id}/{version}"
dashboard_endpoint = prefix + "/api/v1/apps/{app_id}/versions/{version}/dashboard_urls"
all_status_endpoint = prefix + "/api/v1/apps/status/list"

component_links_endpoint = prefix + "/api/v1/apps/{app_id}/component-links"
graphs_schema_endpoint = prefix + "/api/v1/graphs/schema"
node_configs_endpoint = prefix + "/api/v1/node-configs"
node_configs_by_id_endpoint = prefix + "/api/v1/node-configs/{req_uuid}"


forward_directory_endpoint = prefix + "/api/v1/app/{app_id}/flows_service/{flow_title}/directory"
forward_file_endpoint = prefix + "/api/v1/app/{app_id}/flows_service/{flow_title}/file"
forward_git_metadata_endpoint = prefix + \
                                "/api/v1/app/{app_id}/flows_service/{flow_title}/repo-metadata"
forward_git_directory_endpoint = prefix + \
                                 "/api/v1/app/{app_id}/flows_service/{flow_title}/repo-directory"
forward_git_file_endpoint = prefix + "/api/v1/app/{app_id}/flows_service/{flow_title}/repo-file"

input_edge_endpoint = prefix + "/api/v1/app/{app_id}/edge/input/{component}/{edge}"
output_edge_endpoint = prefix + "/api/v1/app/{app_id}/edge/output/{component}/{edge}"

grafana_dashboard_endpoint = prefix + "/api/v1/app/{app_id}/grafana_dashboard"


print(f"list graphs at {app_endpoint}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


kubernetes.config.load_incluster_config()
objs_api = kubernetes.client.CustomObjectsApi()
core_api = kubernetes.client.CoreV1Api()

lock = asyncio.Lock()

logging.basicConfig(format=LOGGING_FORMAT)
LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)


async def pulsar_health_check(flow_title):
    """
    Returns "normal" if pulsar is working for the flow, "error" otherwise
    """
    client = pulsar.Client(PULSAR_CLIENT_SERVICE)
    topic = flow_title.replace("-", "_") + "_healthcheck"
    producer = client.create_producer(topic)
    consumer = client.subscribe(topic, "healthcheck")
    producer.send("Healthcheck".encode("utf-8"))
    msg = consumer.receive()
    try:
        if msg.data().decode("utf-8") == "Healthcheck":
            flow_status = "normal"
        else:
            flow_status = "error"
        # Acknowledge successful processing of the message
        consumer.acknowledge(msg)
    except Exception:
        # Message failed to be processed
        consumer.negative_acknowledge(msg)
        flow_status = "error"
    finally:
        client.close()

    return flow_status


@app.on_event('startup')
async def watch_graphs():
    """Launches a neverending task for watching for all RampartGraph CR changes."""
    asyncio.create_task(watch_graphs_task())


@app.get(all_status_endpoint)
async def get_all_status():
    """Returns the status of all graphs in the cluster."""
    graph_objs = app_db.all()
    tasks = []
    for graph_obj in graph_objs:
        tasks.append(get_app_status(graph_obj["namespace"], graph_obj["name"]))
    graph_states = await asyncio.gather(*tasks)

    result = []
    iter_status = iter(graph_states)
    for graph_obj in graph_objs:
        result += [{
            "id": app_id_from_metadata(graph_obj["graph"]["metadata"]),
            "name": graph_obj["name"],
            "appId": graph_obj.get("app_id"),
            "status": next(iter_status)}]
    return JSONResponse(
        status_code=200,
        content=result)


@app.get(status_endpoint)
async def get_status(app_id):
    """Returns the status of the graph for app `app_id`"""
    try:
        namespace, name, metadata = await get_metadata_from_app_id(app_id)
    except KeyError:
        return JSONResponse(
            status_code=404,
            content={"state": "graph_not_found"})
    try:
        graph_obj = await objs_api.get_namespaced_custom_object(
            "rampart.petuum.com", "v1beta2", namespace, "rampartgraphs", name)
    except kubernetes.client.rest.ApiException as exc:
        if exc.status == 404:
            response_list = []
            graph_query = Query()
            graph_versions = graph_versions_db.search((graph_query.namespace == namespace)
                                                      & (graph_query.name == name))
            for graph_version in sorted(graph_versions, key=itemgetter('version')):
                if graph_version["status"] is not None:
                    response_list.append({"name": name,
                                          "namespace": namespace,
                                          "appId": app_id_from_metadata(metadata),
                                          "version": f"{graph_version['version']}",
                                          "status": STATE_MAP[graph_version["status"]],
                                          "deployed": True if graph_version["status"]
                                          in DEPLOYED_STATES_LIST else False,
                                          "message": "",
                                          "nodes": [],
                                          "flows": []})
            return JSONResponse(status_code=200, content=response_list)
        else:
            return JSONResponse(
                status_code=500,
                content={"message": str(exc.reason)})
    status_obj = graph_obj.get("status", {})
    spec_obj = graph_obj["spec"]
    metadata_obj = graph_obj["metadata"]

    app_status = await get_app_status(namespace, name)
    response = {"name": name,
                "namespace": namespace,
                "readOnly": is_readonly_app(metadata),
                "appId": app_id_from_metadata(metadata_obj),
                "status": app_status,
                "deployed": True if app_status in DEPLOYED_STATES_LIST else False,
                "message": status_obj.get("messages", ""),
                "nodes": [],
                "flows": []}

    num_helm_releases = len(spec_obj["graph"]["components"]) + len(spec_obj["graph"]["flows"])
    num_deployed_releases = 0
    for component, obj in spec_obj["graph"]["components"].items():
        component = component.replace('_', '-')
        if "namespace" not in obj:
            component_ns = "-".join([
                metadata_obj["namespace"], metadata_obj["name"],
                component])
        else:
            component_ns = obj["namespace"]

        component_type = obj.get("type")
        component_status, component_message = await get_component_status(component_ns)

        if component_status == "normal":
            num_deployed_releases += 1

        response["nodes"].append({
            "componentTitle": component,
            "status": component_status,
            "message": component_message,
            "k8sUrl": f"{K8S_DASHBOARD}/#/"
                      f"{COMPONENT_LINKS_TO_DASHBOARD.get(component_type, 'workloads')}"
                      f"?namespace={component_ns}"})

    # flow status
    for flow, obj in spec_obj["graph"]["flows"].items():
        flow_type = obj['type']
        flow = flow.replace('_', '-')
        if "namespace" not in obj:
            flow_ns = "-".join([
                metadata_obj["namespace"], metadata_obj["name"],
                flow])
        else:
            flow_ns = obj["namespace"]

        # repo flow
        if flow_type == "repository":
            base_url = get_flows_service_url(namespace, name, "repository")
            url = "/".join([base_url, flow_ns, "repo-check"])
            try:
                result = await request(url, None)
                if result.status_code == httpx.codes.OK:
                    flow_status = "normal"
                else:
                    flow_status = "error"
            except httpx.RequestError:
                flow_status = "error"
        # pulsar flow
        elif flow_type == "pulsar":
            flow_status = await pulsar_health_check(flow_ns)
        elif flow_type == "volume":
            # TODO: Use an appropriate way to check the status of volume flow
            flow_service_ns = "-".join([metadata_obj["namespace"], metadata_obj["name"],
                                        "rampart", "flows", "volume"])
            flow_status, _ = await get_volume_flows_status(flow_service_ns)
        else:
            flow_status = 'unknown'

        if flow_status == "normal":
            num_deployed_releases += 1

        response["flows"].append({
            "flowTitle": flow,
            "status": flow_status})

    # Progress bar
    if num_helm_releases > 0:
        response["progress"] = round(num_deployed_releases / num_helm_releases, 2)
    else:
        response["progress"] = 0

    response_list = []

    hash_value = dict_hash(graph_obj["spec"]["graph"])
    graph_query = Query()
    graph_versions = graph_versions_db.search((graph_query.namespace == namespace)
                                              & (graph_query.name == name))
    for graph_version in sorted(graph_versions, key=itemgetter('version')):
        if graph_version["hash"] == hash_value:
            response["version"] = f"{graph_version['version']}"
        elif graph_version["status"] is not None:
            response_list.append({"name": name,
                                  "namespace": namespace,
                                  "readOnly": is_readonly_app(metadata),
                                  "appId": app_id_from_metadata(metadata_obj),
                                  "version": f"{graph_version['version']}",
                                  "status": STATE_MAP[graph_version["status"]],
                                  "deployed": True if graph_version["status"]
                                  in DEPLOYED_STATES_LIST else False,
                                  "progress": 0,
                                  "message": "",
                                  "nodes": [],
                                  "flows": []})
    response_list.append(response)
    return JSONResponse(status_code=200, content=response_list)


@app.post(graph_endpoint)
async def create_graph(config_model: GraphModel):
    """Creates a new graph and app given an input graph specification"""
    config = {
        "apiVersion": config_model.apiVersion,
        "kind": config_model.kind,
        "metadata": config_model.metadata,
        "spec": config_model.spec}
    namespace = config["metadata"].get("namespace", "default")
    name = config["metadata"].get("name", "default")
    hash_value = dict_hash(config["spec"]["graph"])
    timestamp = datetime.now(timezone.utc).astimezone().isoformat()

    # Check for duplicate graphs
    graph_query = Query()
    existing_graphs = app_db.search((graph_query.namespace == name) & (graph_query.name == name))
    if len(existing_graphs) > 0:
        return JSONResponse(
            status_code=409,
            content={"state": "duplicate_graph_exists"})

    graph_versions_db.insert({
        "namespace": namespace,
        "name": name,
        "version": 1,
        "hash": hash_value,
        "status": None,
        "active": "False",
        "creationTimestamp": timestamp,
        "lastDeploymentTimestamp": None,
        "graph": {
            "object": filter_metadata(config),
            "timestamp": timestamp,
            "uid": None}
    })

    app_db.insert({
        "uid": None,
        "app_id": app_id_from_metadata(config["metadata"]),
        "namespace": namespace,
        "name": name,
        "desc": "",
        "active": "True",
        "labels": None,
        "graph": filter_metadata(config),
        "lastEditTimestamp": timestamp,
        "lastDeploymentTimestamp": None,
        "activeVersion": 0,
        "versionCount": 1})
    return JSONResponse(
        status_code=201,
        content={
            "graph": config["spec"],
            "appId": app_id_from_metadata(config["metadata"]),
            "versionId": "1"})


@app.get(single_app_endpoint)
async def get_app(app_id):
    """
    Returns all the relevant information about an app:
        name, namespace, deployment status, graph object, all previous versions, modified timestamp
    """
    try:
        namespace, name, metadata = await get_metadata_from_app_id(app_id)
    except KeyError:
        return JSONResponse(
            status_code=404,
            content={"state": "graph_not_found"})
    try:
        graph_obj = await objs_api.get_namespaced_custom_object(
            "rampart.petuum.com", "v1beta2", namespace, "rampartgraphs", name)
        active = graph_obj["spec"].get("deploy", True)
    except kubernetes.client.rest.ApiException as exc:
        if exc.status == 404:
            active = False
        else:
            return JSONResponse(
                status_code=500,
                content={"message": str(exc.reason)})

    if active:
        version = int(graph_obj["metadata"]["generation"])
        graph_query = Query()
        stored_graphs = graph_versions_db.search((graph_query.namespace == namespace)
                                                 & (graph_query.name == name)
                                                 & (graph_query.version == int(version)))

        is_deployed = graph_obj.get("status", {}).get("phase", None) == "Deployed"
        if len(stored_graphs) > 0:
            stored_graph = stored_graphs[0]['graph']
            graph_obj = stored_graph["object"]
            timestamp = stored_graph["timestamp"]
            uid = stored_graph["uid"]
        else:
            timestamp = graph_obj["metadata"]["creationTimestamp"]
            uid = graph_obj["metadata"]["uid"]
            graph_obj = filter_metadata(graph_obj)
    else:
        uid = metadata["uid"]
        graph_obj = {}
        is_deployed = False
        timestamp = metadata.get("lastDeploymentTimestamp")

    graph_query = Query()
    graph_versions = graph_versions_db.search((graph_query.namespace == namespace)
                                              & (graph_query.name == name))
    versions = [
        {
            "name": graph_version["graph"]["object"]["metadata"]["name"],
            "appId": app_id,
            "version": str(graph_version["version"]),
            "status": (STATE_MAP[graph_version["status"]] if graph_version["status"] is not None
                       else (STATE_MAP["Undeployed"] if (graph_version["active"] == "False") else
                       await get_app_status(namespace, name))),
            "deployed": graph_version["active"] == "True",
            "lastDeployment": graph_version.get("lastDeploymentTimestamp"),
            "lastEdit": graph_version.get("creationTimestamp"),
            "notes": ""}
        for graph_version in sorted(graph_versions, key=itemgetter('version'))]
    return JSONResponse(
        status_code=200,
        content={
            "id": uid,
            "name": name,
            "namespace": namespace,
            "readOnly": is_readonly_app(metadata),
            "versions": versions,
            "deployed": is_deployed,
            "graph": graph_obj,
            "lastModified": timestamp})


@app.post(patch_graph_endpoint)
async def patch_app(app_id, config_model: GraphModel):
    """
    Creates a new graph for an existing app. Does not activate the new graph
    """
    #  This endpoint will only work on existing graphs, due to the fact that
    #  app_id is currently also the graph_uid. Therefore, if there is a patch
    #  for an app_id for a graph that doesnt exist, the uid will be different
    #  than the requested app_id
    config = {
        "apiVersion": config_model.apiVersion,
        "kind": config_model.kind,
        "metadata": config_model.metadata,
        "spec": config_model.spec}
    try:
        namespace, name, metadata = await get_metadata_from_app_id(app_id)
        existing_obj = await objs_api.get_namespaced_custom_object(
            "rampart.petuum.com", "v1beta2", namespace, "rampartgraphs", name)
    except KeyError:
        return JSONResponse(
            status_code=404,
            content={"state": "graph_not_found"})
    except kubernetes.client.rest.ApiException as exc:
        if exc.status == 404:
            existing_obj = metadata["graph"]
            existing_obj["metadata"]["uid"] = metadata["uid"]
        else:
            LOG.error(exc.body)
            return JSONResponse(
                status_code=500,
                content=str(exc.reason))
    # Check read-only flag
    if is_readonly_app(metadata):
        return JSONResponse(
            status_code=400,
            content={"state": "graph_read_only"})
    async with lock:
        existing_obj["metadata"]["namespace"] = namespace
        existing_obj["metadata"]["name"] = name
        existing_obj["spec"] = config["spec"]

        new_version = get_latest_version(namespace, name) + 1
        timestamp = datetime.now(timezone.utc).astimezone().isoformat()
        hash_value = dict_hash(existing_obj["spec"]["graph"])

        graph_query = Query()
        graph_versions_db.upsert({
            "namespace": namespace,
            "name": name,
            "version": new_version,
            "hash": hash_value,
            "active": "False",
            "status": None,
            "creationTimestamp": timestamp,
            "lastDeploymentTimestamp": None,
            "graph": {
                "object": filter_metadata(existing_obj),
                "timestamp": timestamp,
                "uid": existing_obj["metadata"]["uid"]}
        },
            (graph_query.namespace == namespace)
            & (graph_query.name == name)
            & (graph_query.version == new_version))

        app_db.update({
            "lastEditTimestamp": timestamp
        }, (graph_query.namespace == namespace)
           & (graph_query.name == name))

        return JSONResponse(
            status_code=200,
            content={
                "appId": app_id,
                "versionId": new_version,
                "graph": filter_metadata(existing_obj)})


@app.delete(single_app_endpoint)
async def delete_app(app_id):
    """
    Deletes an app and all associated graphs
    """
    try:
        namespace, name, metadata = await get_metadata_from_app_id(app_id)
    except KeyError:
        return JSONResponse(
            status_code=404,
            content={"state": "graph_not_found"})
    # Check read-only flag
    if is_readonly_app(metadata):
        return JSONResponse(
            status_code=400,
            content={"state": "graph_read_only"})
    try:
        await objs_api.delete_namespaced_custom_object(
            "rampart.petuum.com", "v1beta2", namespace, "rampartgraphs", name)
    except kubernetes.client.rest.ApiException as exc:
        if exc.status == 404:
            # Clean up the db in case the graph is deleted by the command line
            LOG.error(f"graph {namespace}-{name} not found in kubernetes. Clean up the DB now.")
            graph_query = Query()
            graph_versions_db.remove(
                (graph_query.namespace == namespace) & (graph_query.name == name))
            app_query = Query()
            app_db.remove(app_query.app_id == app_id)
        else:
            LOG.error(exc.body)
            return JSONResponse(
                status_code=500,
                content={"message": str(exc.reason)})
    return JSONResponse(status_code=200,
                        content={"appId": app_id})


@app.get(graph_endpoint)
async def get_graphs():
    """Return all stored graphs"""
    graph_objs = app_db.all()
    result = []
    for graph_obj in graph_objs:
        result += [{
            "id": app_id_from_metadata(graph_obj["graph"]["metadata"]),
            "name": graph_obj["name"],
            "appId": graph_obj.get("app_id"),
            "description": graph_obj["desc"],
            "deployedVersion": graph_obj["activeVersion"],
            "versionCount": graph_obj["versionCount"],
            "readOnly": is_readonly_app(graph_obj),
            "graph": graph_obj["graph"],
            "lastDeployment": graph_obj.get("lastDeploymentTimestamp"),
            "lastEdit": graph_obj.get("lastEditTimestamp")}]

    return JSONResponse(
        status_code=200,
        content=result)


@app.get(app_endpoint)
async def get_apps():
    """Alias for get_graphs"""
    return await get_graphs()


@app.get(version_endpoint)
async def get_versioned_graph(app_id, version):
    """Return the graph for a given app and version"""
    try:
        namespace, name, metadata = await get_metadata_from_app_id(app_id)
    except KeyError:
        return JSONResponse(
            status_code=404,
            content={"state": "graph_not_found"})
    if int(version) == 0:   # Undeployed Graph
        return JSONResponse(
            status_code=200,
            content={
                "appId": app_id,
                "versionId": str(version),
                "graph": {
                    "metadata": {
                        "namespace": namespace,
                        "name": name
                    }
                }})
    async with lock:
        graph_query = Query()
        stored_graphs = graph_versions_db.search((graph_query.namespace == namespace)
                                                 & (graph_query.name == name)
                                                 & (graph_query.version == int(version)))
        if len(stored_graphs) > 0:
            res = stored_graphs[0]['graph']["object"]
            res.pop("status", None)
            return JSONResponse(
                status_code=200,
                content={
                    "appId": app_id,
                    "readOnly": is_readonly_app(metadata),
                    "versionId": str(version),
                    "graph": res})
        else:
            return JSONResponse(
                status_code=404,
                content={"state": "graph not found with that name and version"})


@app.post(redeployment_endpoint)
async def redeploy_graph(app_id, version, redeployModel: RedeployModel):
    """Redeploy or undeploy the graph for a given app and version"""
    try:
        namespace, name, metadata = await get_metadata_from_app_id(app_id)
    except KeyError:
        return JSONResponse(
            status_code=404,
            content={"state": "graph_not_found"})
    # Check read-only flag
    if is_readonly_app(metadata):
        return JSONResponse(
            status_code=400,
            content={"state": "graph_read_only"})
    async with lock:
        # Deploy
        if redeployModel.deployed:
            graph_query = Query()
            stored_graphs = graph_versions_db.search((graph_query.namespace == namespace)
                                                     & (graph_query.name == name)
                                                     & (graph_query.version == int(version)))
            if len(stored_graphs) > 0:
                stored_graph = stored_graphs[0]['graph']
                graph_obj = stored_graph["object"]
                existing_obj = {}
                try:
                    existing_obj = await objs_api.get_namespaced_custom_object(
                        "rampart.petuum.com", "v1beta2", namespace, "rampartgraphs", name)
                except kubernetes.client.rest.ApiException as exc:
                    if exc.status == 404:
                        LOG.info(f"Graph {namespace}-{name} deploying...")
                        version = graph_obj["apiVersion"].split("/")[-1]
                        try:
                            graph_resp = await objs_api.create_namespaced_custom_object(
                                "rampart.petuum.com", version, namespace, "rampartgraphs",
                                graph_obj)
                        except kubernetes.client.rest.ApiException as e:
                            LOG.error(e.body)
                            return JSONResponse(
                                status_code=500,
                                content=str(e.reason))
                        return JSONResponse(
                            status_code=200,
                            content={
                                "appId": app_id,
                                "versionId": graph_resp["metadata"]["generation"],
                                "graph": graph_resp})
                    else:
                        LOG.error(exc.body)
                        return JSONResponse(
                            status_code=500,
                            content={"message": str(exc.reason)})
                try:
                    # Set the status of the previous graph to Undeploying
                    if (dict_hash(existing_obj["spec"]["graph"]) !=
                            dict_hash(graph_obj["spec"]["graph"])):
                        graph_versions_db.update(
                            {"status": "Undeploying"},
                            (graph_query.namespace == namespace)
                            & (graph_query.name == name)
                            & (graph_query.active == "True"))
                    existing_obj["spec"] = graph_obj["spec"]

                    # TODO: only the controller should modify graph status
                    existing_obj["status"]["phase"] = "Deploying"
                    existing_obj["spec"]["deploy"] = True

                    version = existing_obj["apiVersion"].split("/")[-1]
                    graph_resp = await objs_api.replace_namespaced_custom_object(
                        "rampart.petuum.com", version, namespace, "rampartgraphs", name,
                        existing_obj)
                    return JSONResponse(
                        status_code=200,
                        content={
                            "appId": app_id,
                            "versionId": graph_resp["metadata"]["generation"],
                            "graph": graph_resp})
                except kubernetes.client.rest.ApiException:
                    return JSONResponse(
                        status_code=500,
                        content={"state": "error redeploying graph"})
            else:
                return JSONResponse(
                    status_code=404,
                    content={"state": "graph not found with that name and version"})
        # Undeploy
        else:
            try:
                patch = {"spec": {"deploy": False}}
                await objs_api.patch_namespaced_custom_object(
                    "rampart.petuum.com", "v1beta2", namespace, "rampartgraphs", name, patch,
                    _content_type="application/merge-patch+json")
                return JSONResponse(status_code=200,
                                    content={"appId": app_id})
            except kubernetes.client.rest.ApiException as exc:
                LOG.error(exc.body)
                if exc.status == 404:
                    return JSONResponse(
                        status_code=404,
                        content={"state": "graph_not_found"})
                else:
                    return JSONResponse(
                        status_code=500,
                        content={"message": str(exc.reason)})


@app.get(dashboard_endpoint)
async def get_dashboard(app_id, version):
    """Return the kubernetes dashboard for a given app and version"""
    try:
        namespace, name, _ = await get_metadata_from_app_id(app_id)
    except KeyError:
        return JSONResponse(
            status_code=404,
            content={"state": "graph_not_found"})
    async with lock:
        graph_query = Query()
        stored_graphs = graph_versions_db.search((graph_query.namespace == namespace)
                                                 & (graph_query.name == name)
                                                 & (graph_query.version == int(version)))
        if len(stored_graphs) > 0:
            # check if the version is deployed
            if stored_graphs[0]["active"] == "False":
                return JSONResponse(
                    status_code=400,
                    content={"state": f"version {version} is not active"})
        else:
            return JSONResponse(
                status_code=404,
                content={"state": "graph not found with that name and version"})

    k8s_dashboard = f"{K8S_DASHBOARD}/#/workloads?namespace=_all"
    return JSONResponse(
        status_code=200,
        content={"k8s": k8s_dashboard})


@app.get(forward_directory_endpoint)
async def forward_get_volume_tree(app_id, flow_title, path):
    """
    Passes on requests for getting volume flow file trees to the downstream service
    for that flow
    """
    try:
        namespace, name, _ = await get_metadata_from_app_id(app_id)
    except KeyError:
        return JSONResponse(
            status_code=404,
            content={"state": "graph_not_found"})
    base_url = get_flows_service_url(namespace, name, "volume")
    url = "/".join([base_url, flow_title, "directory"])
    params = {'path': path}

    result = await request(url, params)
    if result.status_code == httpx.codes.OK:
        return result.json()
    else:
        return JSONResponse(
            status_code=result.status_code,
            content=result.json())


@app.get(forward_file_endpoint)
async def forward_get_volume_file(app_id, flow_title, path):
    """
    Passes on requests for getting volume flow files to the downstream service
    for that flow
    """
    try:
        namespace, name, _ = await get_metadata_from_app_id(app_id)
    except KeyError:
        return JSONResponse(
            status_code=404,
            content={"state": "graph_not_found"})
    base_url = get_flows_service_url(namespace, name, "volume")
    url = "/".join([base_url, flow_title, "file"])
    params = {'path': path}

    result = await request(url, params)
    if result.status_code == httpx.codes.OK:
        return Response(content=result.content, headers=result.headers)
    else:
        return JSONResponse(
            status_code=result.status_code,
            content=result.json())


@app.get(forward_git_directory_endpoint)
async def forward_get_git_tree(app_id, flow_title, path, branch=None, tag=None):
    """
    Passes on requests for getting git flow trees to the downstream service
    for that flow
    """
    try:
        namespace, name, _ = await get_metadata_from_app_id(app_id)
    except KeyError:
        return JSONResponse(
            status_code=404,
            content={"state": "graph_not_found"})
    base_url = get_flows_service_url(namespace, name, "repository")
    url = "/".join([base_url, flow_title, "repo-directory"])
    params = {'path': path}
    if branch:
        params['branch'] = branch
    if tag:
        params['tag'] = tag

    result = await request(url, params)
    if result.status_code == httpx.codes.OK:
        return result.json()
    else:
        return JSONResponse(
            status_code=result.status_code,
            content=result.json())


@app.get(forward_git_file_endpoint, response_class=FileResponse)
async def forward_get_git_file(app_id, flow_title, path, branch=None, tag=None):
    """
    Passes on requests for getting git flow files to the downstream service
    for that flow
    """
    try:
        namespace, name, _ = await get_metadata_from_app_id(app_id)
    except KeyError:
        return JSONResponse(
            status_code=404,
            content={"state": "graph_not_found"})
    base_url = get_flows_service_url(namespace, name, "repository")
    url = "/".join([base_url, flow_title, "repo-file"])
    params = {'path': path}
    if branch:
        params['branch'] = branch
    if tag:
        params['tag'] = tag

    result = await request(url, params)
    if result.status_code == httpx.codes.OK:
        return Response(content=result.content, headers=result.headers)
    else:
        return JSONResponse(
            status_code=result.status_code,
            content=result.json())


@app.get(forward_git_metadata_endpoint)
async def forward_get_git_metadata(app_id, flow_title):
    """
    Passes on requests for getting git flow metadata to the downstream service
    for that flow
    """
    try:
        namespace, name, _ = await get_metadata_from_app_id(app_id)
    except KeyError:
        return JSONResponse(
            status_code=404,
            content={"state": "graph_not_found"})
    base_url = get_flows_service_url(namespace, name, "repository")
    url = "/".join([base_url, flow_title, "repo-metadata"])

    result = await request(url, None)
    if result.status_code == httpx.codes.OK:
        return result.json()
    else:
        return JSONResponse(
            status_code=result.status_code,
            content=result.json())


@app.get(input_edge_endpoint)
async def forward_get_input_edge_liveness(app_id, component, edge):
    """
    Passes on requests for getting volume flow liveness to the downstream service
    for that flow
    """
    try:
        namespace, name, _ = await get_metadata_from_app_id(app_id)
    except KeyError:
        return JSONResponse(
            status_code=404,
            content={"state": "graph_not_found"})
    try:
        graph_obj = await objs_api.get_namespaced_custom_object(
            "rampart.petuum.com", "v1beta2", namespace, "rampartgraphs", name)
    except kubernetes.client.rest.ApiException as exc:
        if exc.status == 404:
            return JSONResponse(
                status_code=404,
                content={"state": "graph_not_found"})
        else:
            return JSONResponse(
                status_code=500,
                content={"message": str(exc.reason)})

    if component not in graph_obj["spec"]["graph"]["components"]:
        return JSONResponse(
            status_code=404,
            content={"state": "component_not_found"})

    component_obj = graph_obj["spec"]["graph"]["components"][component]
    if "namespace" not in component_obj:
        component_namespace = f"{namespace}-{name}-{component}"
    else:
        component_namespace = component_obj["namespace"]

    base_url = f"http://edges-volume-liveness-service.{component_namespace}.svc.cluster.local:8000"
    path = f"input/{edge}"
    result = await request(f"{base_url}/{path}", None)
    if result.status_code == httpx.codes.OK:
        return result.json()
    else:
        return result.raise_for_status()


@app.get(output_edge_endpoint)
async def forward_get_output_edge_liveness(app_id, component, edge):
    """
    Passes on requests for getting volume flow liveness to the downstream service
    for that flow
    """
    try:
        namespace, name, _ = await get_metadata_from_app_id(app_id)
    except KeyError:
        return JSONResponse(
            status_code=404,
            content={"state": "graph_not_found"})
    try:
        graph_obj = await objs_api.get_namespaced_custom_object(
            "rampart.petuum.com", "v1beta2", namespace, "rampartgraphs", name)
    except kubernetes.client.rest.ApiException as exc:
        if exc.status == 404:
            return JSONResponse(
                status_code=404,
                content={"state": "graph_not_found"})
        else:
            return JSONResponse(
                status_code=500,
                content={"message": str(exc.reason)})

    if component not in graph_obj["spec"]["graph"]["components"]:
        return JSONResponse(
            status_code=404,
            content={"state": "component_not_found"})

    component_obj = graph_obj["spec"]["graph"]["components"][component]
    if "namespace" not in component_obj:
        component_namespace = f"{namespace}-{name}-{component}"
    else:
        component_namespace = component_obj["namespace"]

    base_url = f"http://edges-volume-liveness-service.{component_namespace}.svc.cluster.local:8000"
    path = f"output/{edge}"
    result = await request(f"{base_url}/{path}", None)
    if result.status_code == httpx.codes.OK:
        return result.json()
    else:
        return result.raise_for_status()


@app.get(grafana_dashboard_endpoint)
async def get_grafana_dashboard(app_id):
    """Returns the grafana dashboard for an app"""
    try:
        namespace, name, _ = await get_metadata_from_app_id(app_id)
    except KeyError:
        return JSONResponse(
            status_code=404,
            content={"state": "graph_not_found"})

    dashboard_query = Query()
    dashboard_list = dashboard_db.search(dashboard_query.app_id == app_id)
    if not dashboard_list:
        return JSONResponse(
            status_code=404,
            content={"state": "dashboard_not_found"})
    else:
        assert (len(dashboard_list) == 1), f"Found more than one dashboard for app_id {app_id}"
        dashboard = dashboard_list[0]
        urls = dashboard["urls"]
    return json.loads(urls)


@app.get(graphs_schema_endpoint)
async def get_graphs_schema():
    """Returns the current graph syntatic schema"""
    return FileResponse("./schema.json")


@app.post(node_configs_endpoint)
async def create_node_configs(node_configs_req: NodeConfigsModel):
    """Creates and stores a node config"""
    uuid_str = generate_uuid_str()
    timestamp = datetime.now(timezone.utc).astimezone().isoformat()
    res = {"id": uuid_str,
           "title": node_configs_req.title,
           "config": node_configs_req.config,
           "type": node_configs_req.type,
           "nodeType": node_configs_req.nodeType,
           "message": node_configs_req.message,
           "creationTimestamp": timestamp,
           "lastModifiedTimestamp": None,
           "version": 1}
    async with lock:
        configs_query = Query()
        configs_db.upsert(res, configs_query.id == uuid_str)
    return JSONResponse(
        status_code=200,
        content=res)


@app.get(node_configs_by_id_endpoint)
async def get_node_configs_by_id(req_uuid):
    configs_query = Query()
    configs_list = configs_db.search(configs_query.id == req_uuid)
    if not configs_list:
        return JSONResponse(
            status_code=404,
            content={"state": "configs_not_found"})
    else:
        if len(configs_list) > 1:
            return JSONResponse(
                status_code=500,
                content={"state": f"Found more than one configs for uuid {req_uuid}"}
            )
        configs = configs_list[0]
        return JSONResponse(
            status_code=200,
            content=configs)


@app.put(node_configs_by_id_endpoint)
async def modify_node_configs_by_id(req_uuid, node_configs_req: NodeConfigsModel):
    configs_query = Query()
    configs_list = configs_db.search(configs_query.id == req_uuid)
    if not configs_list:
        return JSONResponse(
            status_code=404,
            content={"state": "configs_not_found"})
    else:
        if len(configs_list) > 1:
            return JSONResponse(
                status_code=500,
                content={"state": f"Found more than one configs for uuid {req_uuid}"}
            )
        configs = configs_list[0]
        configs["title"] = node_configs_req.title
        configs["config"] = node_configs_req.config
        configs["type"] = node_configs_req.type
        configs["nodeType"] = node_configs_req.nodeType
        configs["message"] = node_configs_req.message

        timestamp = datetime.now(timezone.utc).astimezone().isoformat()
        configs["lastModifiedTimestamp"] = timestamp
        configs["version"] += 1

        configs_db.upsert(configs, configs_query.id == req_uuid)
        return JSONResponse(
            status_code=200,
            content=configs)


@app.get(node_configs_endpoint)
async def list_node_configs():
    configs_list = configs_db.all()
    return configs_list


@app.delete(node_configs_by_id_endpoint)
async def delete_node_configs_by_id(req_uuid):
    configs_query = Query()
    configs_list = configs_db.search(configs_query.id == req_uuid)
    if not configs_list:
        return JSONResponse(
            status_code=404,
            content={"state": "configs_not_found"})
    else:
        if len(configs_list) > 1:
            return JSONResponse(
                status_code=500,
                content={"state": f"Found more than one configs for uuid {req_uuid}"}
            )
        configs_db.remove(configs_query.id == req_uuid)
        return Response(status_code=204)


@app.get(component_links_endpoint)
async def get_component_links(app_id):
    """
    Returns all the endpoints that a component exposes.
    """
    try:
        # TODO: change the name of the third result away from metadata
        namespace, name, metadata = await get_metadata_from_app_id(app_id)
        existing_obj = await objs_api.get_namespaced_custom_object(
            "rampart.petuum.com", "v1beta2", namespace, "rampartgraphs", name)
    except KeyError:
        return JSONResponse(
            status_code=404,
            content={"state": "graph_not_found"})
    except kubernetes.client.rest.ApiException as exc:
        if exc.status == 404:
            return JSONResponse(
                status_code=404,
                content={"state": "graph_not_found"})
        else:
            LOG.error(exc.body)
            return JSONResponse(
                status_code=500,
                content=str(exc.reason))

    result = []
    # parse json
    if "status" in existing_obj and "endpointPaths" in existing_obj["status"]:
        endpoint_paths_str = existing_obj["status"].get("endpointPaths")
        endpoint_paths_obj = json.loads(endpoint_paths_str)
        for component, endpoints in endpoint_paths_obj.items():
            result.append({
                "component": component,
                "endpoints": endpoints
            })

    return JSONResponse(
        status_code=200,
        content=result)
