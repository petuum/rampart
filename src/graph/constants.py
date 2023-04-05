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

import json
import os
import pathlib
import re

import aiohttp
import jsonschema
import yamale

""" Graph CRD """
RAMPART_CRD_KIND = "RampartGraph"
RAMPART_CRD_API = "rampart.petuum.com/v1beta2"
RAMPART_CRD_VERSION = "v1beta2"
DEPRECATED_RAMPART_CRD_VERSIONS = ["v1beta1"]


""" Core """
IMAGE_PULL_SECRET_PATH = os.environ.get("RAMPART_IMAGE_PULL_SECRET_PATH", "")
RAMPART_REGISTRY = os.environ.get("RAMPART_REGISTRY", "")
STORAGE_CLASS = os.environ.get("RAMPART_STORAGE_CLASS", "rampart")
WORKDIR = os.environ.get("RAMPART_WORKDIR", "")

# Flows
RAMPART_FLOW_IMAGE = os.environ.get("RAMPART_FLOW_IMAGE", "")
FLOW_NAME_RE = re.compile(r"[a-zA-Z0-9_-]*")

# Controller
CONTROLLER_IMAGE = os.environ.get("RAMPART_CONTROLLER_IMAGE", "")  # TODO: Not used
# TODO: CONTROLLER_NAMESPACE should ideally be passed down from rampart-helm
try:
    with open("/var/run/secrets/kubernetes.io/serviceaccount/namespace", "r") as f:
        CONTROLLER_NAMESPACE = f.readline().strip()
except FileNotFoundError:
    # We are not in kubernetes
    CONTROLLER_NAMESPACE = "NO_NAMESPACE_FOUND"


# Infra Graph
def RAMPART_INFRA_K8S_KEY_GEN(namespace):
    return ("rampart.petuum.com", "v1beta1", namespace, "rampartinfras")


# Kubernetes annotation key
COMPONENT_SPEC_KEY = "petuum.com/rampartComponent"
# Kubernetes finalizer key to signal pre-deletion operation
FINALIZER = "rampart.petuum.com/graph"
HELMFILE_TEMPLATE = {
    "name": None,
    "namespace": None,
    "createNamespace": False,
    "labels": [],
    "chart": None,
    "version": None,
    "values": []
}
UNICODE_PARAGRAPH_SEPARATOR_CLASS_CHARACTERS = u"\u000a\u000d\u001c\u001d\u001e\u0085\u2028\u2029"
# Kubernetes label selectors
CONTROLLED_BY_RAMPART = "controlled-by-rampart=true"


""" Timeouts """
HTTP_TIMEOUT = aiohttp.ClientTimeout(10.0)
REPO_TIMEOUT = int(os.environ.get("RAMPART_REPO_TIMEOUT", 60))
REPO_FLOW_INIT_TIMEOUT = int(os.environ.get("RAMPART_REPO_FLOW_INIT_TIMEOUT", 600))
COMPONENT_INSTALL_TIMEOUT = int(os.environ.get("RAMPART_COMPONENT_INSTALL_TIMEOUT", 600))
INFRA_LOCK_TIMEOUT = 10.0
NS_TERMINATION_TIMEOUT = 60
PATCH_RETRY_TIMEOUT = 10.0

""" Secrets """
_SECRET_PREFIX = "rampart-internal"
REPO_FLOW_SECRET_NAME = f"{_SECRET_PREFIX}-repo-flow-secret"
REPO_EDGE_SECRET_NAME = f"{_SECRET_PREFIX}-repo-edge-secret"
PULL_IMAGE_SECRET_NAME = f"{_SECRET_PREFIX}-stagingsecret"


""" Paths """
VOLUME_FLOW_LIVENESS_PATH = os.environ.get(
    "RAMPART_VOLUME_FLOW_LIVENESS_PATH", "src/graph_service/flows/volume_flow_liveness.py")


""" Pulsar """
_PULSAR_SERVICE = os.environ.get("RAMPART_PULSAR_SERVICE", "")
PULSAR_ADMIN_PORT = os.environ.get("RAMPART_PULSAR_ADMIN_PORT", "")
PULSAR_CLIENT_PORT = os.environ.get("RAMPART_PULSAR_CLIENT_PORT", "")
PULSAR_DEPLOYMENT = os.environ.get("RAMPART_PULSAR_DEPLOYMENT", "rampart-pulsar")
PULSAR_NAMESPACE = os.environ.get("RAMPART_PULSAR_NAMESPACE", "pulsar")
PULSAR_TENANT = "rampart"

if (not PULSAR_ADMIN_PORT) != (not PULSAR_CLIENT_PORT):
    raise RuntimeError(f"Pulsar admin port is '{PULSAR_ADMIN_PORT}' and pulsar client port is "
                       f"'{PULSAR_CLIENT_PORT}'. Both must be either empty or set")

# TODO: Support generic DNS format for pulsar endpoint
if PULSAR_ADMIN_PORT:
    PULSAR_ADMIN_SERVICE = \
        f"{_PULSAR_SERVICE}.{PULSAR_NAMESPACE}.svc.cluster.local:{PULSAR_ADMIN_PORT}"
    PULSAR_CLIENT_SERVICE = \
        f"{_PULSAR_SERVICE}.{PULSAR_NAMESPACE}.svc.cluster.local:{PULSAR_CLIENT_PORT}"
else:
    PULSAR_ADMIN_SERVICE = f"{_PULSAR_SERVICE}.{PULSAR_NAMESPACE}.svc.cluster.local"
    PULSAR_CLIENT_SERVICE = PULSAR_ADMIN_SERVICE


def GENERATE_PULSAR_NAMESPACE(metadata):
    return f"{PULSAR_TENANT}/{metadata.namespace.original_view}_{metadata.name.original_view}"


""" HNS """
HNS_API = "hnc.x-k8s.io"
HNS_VERSION = "v1alpha2"
HNS_KIND_SN = "SubnamespaceAnchor"
HNS_KIND_PL = HNS_KIND_SN.lower() + "s"
HNS_TEMPLATE = {
    "apiVersion": f"{HNS_API}/{HNS_VERSION}",
    "kind": HNS_KIND_SN,
    "metadata": {}
}

""" Jsonschema """
JSONSCHEMA_LOCAL_BASE_URI = pathlib.Path(__file__).parent
# This setup works for one schema file. To support multiple, use the RefResolver.
# Note the RefResolver does not resolve non-local ids, i.e.
# https://rampart.petuum.com/rampart-schemas/graph.json given a base directory
# out of the box.
with open(pathlib.Path(__file__).with_name('graph.json')) as schema_file:
    GRAPH_JSONSCHEMA = json.load(schema_file)
    jsonschema.Draft202012Validator.check_schema(GRAPH_JSONSCHEMA)
    JSONSCHEMA_VALIDATOR = jsonschema.Draft202012Validator(schema=GRAPH_JSONSCHEMA)

""" Apisix """
APISIX_ROUTE_API = "apisix.apache.org"
APISIX_ROUTE_VERSION = "v2beta3"
APISIX_ROUTE_KIND_SN = "ApisixRoute"
APISIX_ROUTE_KIND_PL = APISIX_ROUTE_KIND_SN.lower() + "s"
APISIX_ROUTE_TEMPLATE = {
    "apiVersion": f"{APISIX_ROUTE_API}/{APISIX_ROUTE_VERSION}",
    "kind": APISIX_ROUTE_KIND_SN,
    "metadata": {}
}

""" Aux Chart """
AUX_CHART_REPO = os.environ.get("RAMPART_AUX_CHART_REPO", "rampart-repo")
AUX_CHART_NAME = os.environ.get("RAMPART_AUX_CHART_NAME", "auth-aux")
# AUX_CHART_VERSION = "0.6.0-20221118a"
AUX_CHART_VERSION = os.environ.get("RAMPART_AUX_CHART_VERSION", "latest")
AUX_CHART_COMP_KEY = "auth-aux"

""" Component Annotations Schema """
COMP_ANNOTATIONS_SCHEMA_PATH = os.path.join(pathlib.Path(__file__).parent.absolute(),
                                            "component_annotations_schema.yaml")
COMP_ANNOTATIONS_SCHEMA = yamale.make_schema(COMP_ANNOTATIONS_SCHEMA_PATH)


""" Utility """
LOGGING_FORMAT = '%(asctime)s:  %(message)s'
