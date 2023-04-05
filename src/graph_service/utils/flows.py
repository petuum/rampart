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

def get_flows_service_url(namespace, name, flow_type):
    flows_service_name = f"flows-{flow_type}-flows-service"
    flows_service_namespace = "-".join([namespace, name, "rampart", "flows", flow_type])
    base_url = ".".join([flows_service_name, flows_service_namespace, "svc", "cluster", "local"])
    port = 8000
    url = "http://" + base_url + ":" + str(port) + "/api/v1/app/flows_service"
    return url
