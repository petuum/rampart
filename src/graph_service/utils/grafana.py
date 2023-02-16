# Copyright 2023 Petuum, Inc. All Rights Reserved.

import json
import logging

from tinydb import TinyDB, Query

from grafana_dashboard.service import NAME_MAP as GRAFANA_NAME_MAP, get_or_create_dashboard, \
    DCGM_METRICS
from .constants import LOGGING_FORMAT

dashboard_db = TinyDB('/etc/graphs/dashboard.json')

logging.basicConfig(format=LOGGING_FORMAT)
LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)


async def create_or_modify_grafana_dashboard(namespace, name, app_id,
                                             generation, component_namespaces):
    dashboard_query = Query()
    dashboard_list = dashboard_db.search(dashboard_query.app_id == app_id)
    if not dashboard_list:
        dashboard_id = None
        dashboard_uid = None
        dashboard_version = 0
        prev_generation = generation
    else:
        assert (len(dashboard_list) == 1), f"Found more than one dashboard for app_id {app_id}"
        dashboard = dashboard_list[0]
        prev_generation = dashboard["generation"]
        dashboard_id = dashboard["dashboard_id"]
        dashboard_uid = dashboard["dashboard_uid"]
        dashboard_version = dashboard["dashboard_version"]
        if generation > prev_generation:
            dashboard_version += 1

    response = await get_or_create_dashboard(namespace, name, component_namespaces,
                                             dashboard_id, dashboard_uid, dashboard_version)
    if "message" in response:
        LOG.error(response["message"])
    uid = response["dashboard"]["uid"]

    urls = {}
    missing_gpu_metrics = set(DCGM_METRICS.values())
    for panel in response["dashboard"]["panels"]:
        title = panel["title"]
        if title in missing_gpu_metrics:
            missing_gpu_metrics.remove(title)
        urls[GRAFANA_NAME_MAP[title]] = (
            f"/grafana/d-solo/{uid}/new-dashboard?orgId=1&panelId={panel['id']}")
    for metric in missing_gpu_metrics:
        urls[GRAFANA_NAME_MAP[metric]] = None

    urls = json.dumps(urls)

    if urls:
        dashboard_query = Query()
        dashboard_db.upsert({
            "app_id": app_id,
            "generation": generation,
            "dashboard_id": response["dashboard"]["id"],
            "dashboard_uid": uid,
            "dashboard_version": response["dashboard"]["version"],
            "urls": urls},
            (dashboard_query.app_id == app_id))
    else:
        raise RuntimeError(str(f"{namespace}/{name} {response}"))
