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

import os


DASHBOARD_HOSTNAME = os.environ.get("DASHBOARD_HOSTNAME", None)
DASHBOARD_PORT = os.environ.get("DASHBOARD_PORT", None)
DASHBOARD_PATH = os.environ.get("DASHBOARD_PATH", "")
if DASHBOARD_PATH:
    DASHBOARD_PATH = DASHBOARD_PATH.strip("/")

if DASHBOARD_HOSTNAME and DASHBOARD_PORT and DASHBOARD_PATH:
    K8S_DASHBOARD = f"http://{DASHBOARD_HOSTNAME}:{DASHBOARD_PORT}/{DASHBOARD_PATH}"
elif DASHBOARD_HOSTNAME and not DASHBOARD_PORT:
    K8S_DASHBOARD = f"http://{DASHBOARD_HOSTNAME}/{DASHBOARD_PATH}"
else:
    if DASHBOARD_PATH:
        K8S_DASHBOARD = f"/{DASHBOARD_PATH}"
    else:
        K8S_DASHBOARD = DASHBOARD_PATH

PULSAR_NAMESPACE = os.environ.get("RAMPART_PULSAR_NAMESPACE", "pulsar")
PULSAR_ADMIN_PORT = os.environ.get("RAMPART_PULSAR_ADMIN_PORT", "")
PULSAR_CLIENT_PORT = os.environ.get("RAMPART_PULSAR_CLIENT_PORT", "")
_PULSAR_SERVICE = os.environ.get("RAMPART_PULSAR_SERVICE", "")
if PULSAR_ADMIN_PORT:
    PULSAR_CLIENT_SERVICE = \
        f"pulsar://{_PULSAR_SERVICE}.{PULSAR_NAMESPACE}.svc.cluster.local:{PULSAR_CLIENT_PORT}"
else:
    PULSAR_CLIENT_SERVICE = f"pulsar://{_PULSAR_SERVICE}.{PULSAR_NAMESPACE}.svc.cluster.local"


STATE_MAP = {None: "undeployed",
             "Undeployed": "undeployed",
             "Deployed": "deployed",
             "Deploying": "deploying",
             "Undeploying": "undeploying",
             "DeployedWithErrors": "deployment_error",
             "Deleting": "deleting",
             "Failed": "error"}

DEPLOYED_STATES_LIST = {"deployed", "deploying", "deployment_error", "error"}

COMPONENT_STATE_MAP = {None: "not_found",
                       "Normal": "normal",
                       "DeployedWithTransientErrors": "transient_error",
                       "DeployedWithPersistentErrors": "persistent_error",
                       "NotFound": "not_found",
                       "Installing": "deploying",
                       "Failed": "error"}

COMPONENT_LINKS_TO_DASHBOARD = {
    "batch-uploader": "deployment",
    "batch-executor": "workloads",
    "experiment-manager": "workloads",
    "generic-service": "deployment",
    "symphony": "workloads",
    "tensorboard": "deployment"
}

TIMEOUT = 20

LOGGING_FORMAT = '%(asctime)s:  %(message)s'
