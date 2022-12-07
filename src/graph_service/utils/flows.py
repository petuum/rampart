# Copyright 2023 Petuum, Inc. All Rights Reserved.

def get_flows_service_url(namespace, name, flow_type):
    flows_service_name = f"flows-{flow_type}-flows-service"
    flows_service_namespace = "-".join([namespace, name, "rampart", "flows", flow_type])
    base_url = ".".join([flows_service_name, flows_service_namespace, "svc", "cluster", "local"])
    port = 8000
    url = "http://" + base_url + ":" + str(port) + "/api/v1/app/flows_service"
    return url
