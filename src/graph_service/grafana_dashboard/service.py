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

"""
Provides functionality for adding, modifying, and deleting Grafana dashboards for Rampart
graphs.

As the graphs are created and updated, we need to automatically create and update Grafana
dashboards such that they cover all of the component namespaces of the graph.
"""

import asyncio
import copy
import httpx
import json
import os

import logging


LOGGING_FORMAT = '%(asctime)s:  %(message)s'
logging.basicConfig(format=LOGGING_FORMAT)
LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)


DCGM_METRICS = {
    "DCGM_FI_DEV_GPU_UTIL": "GPU Utilization",
    "DCGM_FI_DEV_POWER_USAGE": "GPU Power Usage",
    "DCGM_FI_DEV_FB_USED": "GPU Memory Usage"}

NAME_MAP = {
    "GPU Utilization": "gpuUtilization",
    "GPU Power Usage": "gpuPowerUsage",
    "GPU Memory Usage": "gpuMemoryUsage",
    "CPU Usage": "cpuUsage",
    "Memory Usage": "memoryUsage",
    "Deployment Status": "deploymentStatus"}

# TODO: make this robust to different grafana namespaces
controller_namespace = os.environ["RAMPART_CONTROLLER_NAMESPACE"]
GRAFANA_NAMESPACE = f"{controller_namespace}-infra-grafana"


async def get_dcgm_metrics():
    """
    Return all gpu (NVIDIA Data Center GPU Manager) metrics that we have access to
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"http://component-prometheus-server.{GRAFANA_NAMESPACE}.svc.cluster.local:80"
            "/api/v1/metadata")

    metrics = response.json()["data"]
    return [metric for metric in metrics if metric in DCGM_METRICS]


async def create_dashboard(graph_namespace, graph_name, component_namespaces,
                           dashboard_id=None, dashboard_uid=None, version=0):
    """
    Generate the payload for creating or updating a Grafana dashboard for a given graph
    and component.

    Setting dashboard_id, dashboard_uid, and version will update instead of create
    """
    dir_path = os.path.dirname(os.path.realpath(__file__))
    with open(os.path.join(dir_path, "usage_template.json")) as f:
        template = json.load(f)
    # TODO: get datasource UID

    controller_namespace = os.environ["RAMPART_CONTROLLER_NAMESPACE"]
    controller_name = os.environ["RAMPART_CONTROLLER_DEPLOYMENT"]

    template["title"] = f"{graph_namespace}/{graph_name} " + template["title"]
    template["version"] = version

    template["id"] = dashboard_id
    template["uid"] = dashboard_uid

    template["panels"][0]["targets"][0]["expr"] = (
        f'{{job="{controller_namespace}/{controller_name}"}} '
        f'|= `graph_namespace={graph_namespace}` |= `graph_name={graph_name} `')

    template["panels"][1]["targets"][0]["expr"] = (
        'sum by(namespace) (rate(container_cpu_usage_seconds_total{namespace=~"'
        f'{"|".join(component_namespaces)}", cpu="total", image!=""'
        '}[5m]))')

    template["panels"][2]["targets"][0]["expr"] = (
        'sum by(namespace) (container_memory_usage_bytes{namespace=~"'
        f'{"|".join(component_namespaces)}", image!=""'
        '})')

    gpu_metrics = await get_dcgm_metrics()
    if gpu_metrics:
        with open(os.path.join(dir_path, "gpu_template.json")) as f:
            gpu_target_template = json.load(f)
        template["panels"][3:] = [copy.deepcopy(gpu_target_template) for i in gpu_metrics]
        for panel, metric in enumerate(gpu_metrics):
            template["panels"][3+panel]["targets"][0]["expr"] = metric
            template["panels"][3+panel]["title"] = DCGM_METRICS[metric]
            template["panels"][3+panel]["id"] = 4 + panel

    return template


async def create_and_get_dashboard(namespace, name, component_namespaces,
                                   dashboard_id, dashboard_uid, version):

    """
    Creates or updates a dashboard for a graph with a given set of components, and returns
    the response from the Grafana api
    """
    template = await create_dashboard(namespace, name, component_namespaces,
                                      dashboard_id, dashboard_uid, version)

    # TODO: allow retries
    url = (
        f"http://admin:admin@component-grafana.{GRAFANA_NAMESPACE}"
        ".svc.cluster.local/grafana/api/dashboards/db")

    data = {"dashboard": template, "overwrite": True}

    async with httpx.AsyncClient() as client:
        LOG.info(f"Creating dashboard for {namespace}/{name} with version {version}")
        response = await client.post(url, json=data)
        response = response.json()
        LOG.info(f"received {response}")

    if "uid" in response:
        dashboard_uid = response["uid"]
    else:
        raise RuntimeError(f"Could not create dashboard: {response}")

    found = False
    retries = 10
    while not found and retries:
        url = (
            f"http://admin:admin@component-grafana.{GRAFANA_NAMESPACE}"
            f".svc.cluster.local/grafana/api/dashboards/uid/{dashboard_uid}")

        async with httpx.AsyncClient() as client:
            response = await client.get(url)

        found = response.status_code >= 200 and response.status_code < 300
        if found:
            return response.json()
        await asyncio.sleep(5)
        retries -= 1

    raise RuntimeError("Not found")


async def get_or_create_dashboard(namespace, name, component_namespaces,
                                  dashboard_id, dashboard_uid, version):
    """
    Tries to get the existing dashboard for a component.
    If that fails, then create new dashboards first.
    """
    url = (
        f"http://admin:admin@component-grafana.{GRAFANA_NAMESPACE}"
        f".svc.cluster.local/grafana/api/dashboards/uid/{dashboard_uid}")

    LOG.info(f"Fetching dashboard for {namespace}/{name}")
    async with httpx.AsyncClient() as client:
        response = await client.get(url)

    found = response.status_code >= 200 and response.status_code < 300
    if found:
        found_version = response.json()["meta"]["version"]
        LOG.info(f"Found dashboard for {namespace}/{name} with version {found_version}")

    if not found or version != found_version:
        LOG.info(f"Cannot find dashboard for {namespace}/{name} with version {version}")
        return await create_and_get_dashboard(
            namespace, name, component_namespaces, dashboard_id, dashboard_uid, version=version)
    else:
        return response.json()


async def delete_dashboard(uid):
    """Deletes a dashboard"""
    url = (
        f"http://admin:admin@component-grafana.{GRAFANA_NAMESPACE}"
        f".svc.cluster.local/grafana/api/dashboards/uid/{uid}")

    async with httpx.AsyncClient() as client:
        response = await client.delete(url)
    return response.json()
