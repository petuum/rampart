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
import argparse
import base64
import copy
import json
import logging
import ssl
import time

from http import HTTPStatus
import kubernetes_asyncio as kubernetes

from aiohttp import web

LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)

kubernetes.config.load_incluster_config()
custom_api = kubernetes.client.CustomObjectsApi()
core_api = kubernetes.client.CoreV1Api()


class MutatingWebhook(object):
    # This class watches for pod creations, and when a pod is created,
    # it modifies the pod spec to use the mutationpreset in that namespace.
    #
    # Dictionaries/Lists will be merged between the two, with dictionary's
    # using the preset's value in case of key collisions. Note: this does not
    # support deeply nested merges.
    #
    # Currently, it only supports a single mutationpreset per namespace,
    # and subnamespaces do not inherent from their parents. The former ideally
    # is fixed, but then that gets into a few tricky questions about precedence
    # in collisions.
    def __init__(self):
        self._app = web.Application()
        self._app.add_routes([
            web.get('/healthz', self._handle_healthz),
            web.post('/mutate/pod', self._handle_mutate_pod),
            web.post('/mutate/ingress', self._handle_mutate_ingress),
        ])

    def get_app(self):
        return self._app

    def run(self, host, port, ssl_context=None):
        web.run_app(self.get_app(), host=host, port=port, ssl_context=ssl_context)

    async def _handle_healthz(self, request):
        # Health check.
        return web.Response()

    async def _handle_mutate_pod(self, request):
        request_json = await request.json()
        start = time.time()
        if request_json["request"]["operation"] == "CREATE":
            response = await self._mutate_create_pod(request_json["request"])
        else:
            response = {"allowed": True}
        response["uid"] = request_json["request"]["uid"]
        duration = time.time() - start
        LOG.info("%s %s %s: %s",
                 request_json["request"]["operation"],
                 request_json["request"]["namespace"],
                 "elapsed",
                 duration)
        return web.json_response({
            "apiVersion": "admission.k8s.io/v1",
            "kind": "AdmissionReview",
            "response": response,
        })

    def _create_pod_patch(self, container_preset, pod_preset, object_spec, has_gpus):
        object_container_spec = object_spec["containers"]
        object_init_container_spec = object_spec.get("initContainers", [])
        object_pod_spec = object_spec
        patch = []

        for i, container in enumerate(object_container_spec):
            if (has_gpus and
                    "nvidia.com/gpu" not in container.get("resources", {}).get("limits", {}) and
                    "nvidia.com/gpu" not in
                    container_preset.get("resources", {}).get("limits", {})):
                preset = copy.deepcopy(container_preset)
                if "resources" not in preset:
                    preset["resources"] = {}
                if "limits" not in preset["resources"]:
                    preset["resources"]["limits"] = {}
                preset["resources"]["limits"]["nvidia.com/gpu"] = 0
            else:
                preset = container_preset
            for key, value in preset.items():
                if key not in container:
                    patch.append(
                        {"op": "add",
                         "path": f"/spec/containers/{i}/{key}",
                         "value": value})
                elif type(value) == list:
                    for elem in value:
                        if all([elem != existing_value
                                for existing_value in container[key]]):
                            patch.append(
                                {"op": "add",
                                 "path": f"/spec/containers/{i}/{key}/0",
                                 "value": elem})
                elif type(value) == dict:
                    for elem_key, elem_value in value.items():
                        patch.append(
                            {"op": "add",
                             "path": ("/spec/containers/"
                                      f"{i}/{key}/{elem_key}"),
                             "value": elem_value})

        for i, container in enumerate(object_init_container_spec):
            if (has_gpus and
                    "nvidia.com/gpu" not in container.get("resources", {}).get("limits", {}) and
                    "nvidia.com/gpu" not in
                    container_preset.get("resources", {}).get("limits", {})):
                preset = copy.deepcopy(container_preset)
                if "resources" not in preset:
                    preset["resources"] = {}
                if "limits" not in preset["resources"]:
                    preset["resources"]["limits"] = {}
                preset["resources"]["limits"]["nvidia.com/gpu"] = 0
            else:
                preset = container_preset
            for key, value in preset.items():
                if key not in container:
                    patch.append(
                        {"op": "add",
                         "path": f"/spec/initContainers/{i}/{key}",
                         "value": value})
                elif type(value) == list:
                    for elem in value:
                        if all([elem != existing_value
                                for existing_value in container[key]]):
                            patch.append(
                                {"op": "add",
                                 "path": f"/spec/initContainers/{i}/{key}/0",
                                 "value": elem})
                elif type(value) == dict:
                    for elem_key, elem_value in value.items():
                        patch.append(
                            {"op": "add",
                             "path": ("/spec/initContainers/"
                                      f"{i}/{key}/{elem_key}"),
                             "value": elem_value})

        for key, value in pod_preset.items():
            if key not in object_pod_spec:
                patch.append(
                    {"op": "add",
                     "path": f"/spec/{key}",
                     "value": value})
            elif type(value) == list:
                for preset in value:
                    if all([preset != existing_value for existing_value in object_pod_spec[key]]):
                        patch.append(
                            {"op": "add", "path": f"/spec/{key}/0",
                             "value": preset})
            elif type(value) == dict:
                for elem_key, elem_value in value.items():
                    patch.append(
                        {"op": "add",
                         "path": (f"/spec/{key}/{elem_key}"),
                         "value": elem_value})
        return patch

    async def _mutate_create_pod(self, request):
        response = {}
        namespace = request["namespace"]

        async def wait_for_mutation_preset():
            resp = await custom_api.list_namespaced_custom_object(
                            "rampart.petuum.com", "v1beta1", namespace,
                            "mutationpresets")
            presets = resp["items"]
            # TODO: consider adding a timeout for the loop
            while len(presets) == 0:
                resp = await custom_api.list_namespaced_custom_object(
                            "rampart.petuum.com", "v1beta1", namespace,
                            "mutationpresets")
                presets = resp["items"]
                await asyncio.sleep(0.1)
            # TODO: allow multiple mutation presets, if necessary
            preset = presets[0]["spec"]
            return preset

        async def check_nvidia_gpus():
            nodes = await core_api.list_node()
            for node in nodes.items:
                if "nvidia.com/gpu" in node.status.capacity:
                    return True
            return False
        preset, has_gpus = await asyncio.gather(wait_for_mutation_preset(), check_nvidia_gpus())
        container_preset = preset["containerTemplate"]
        pod_preset = preset["podTemplate"]
        for volume in pod_preset["volumes"]:
            if "persistentVolumeClaim" in volume:
                pvc_name = volume["persistentVolumeClaim"]["claimName"]
                try:
                    pvc_object = \
                        await core_api.read_namespaced_persistent_volume_claim(pvc_name, namespace)
                    if pvc_object.metadata.deletion_timestamp:
                        return {"allowed": False,
                                "status": {
                                    "code": HTTPStatus.FORBIDDEN,
                                    "reason": "Cannot attach a PVC that is scheduled for deletion",
                                    "message": (
                                        "Pod creation failed: "
                                        "cannot attach a PVC that is scheduled for deletion")
                                          }
                                }
                except kubernetes.client.rest.ApiException as exc:
                    if exc.status == 404:
                        pass
                    else:
                        raise exc
        try:
            patch = self._create_pod_patch(container_preset,
                                           pod_preset, request["object"]["spec"], has_gpus)
        except RuntimeError as e:
            if e.args == ("Disallowed",):
                return {"allowed": False}
        patch_str = json.dumps(patch)
        response["patch"] = base64.b64encode(patch_str.encode()).decode()
        response["patchType"] = "JSONPatch"
        response["allowed"] = True
        return response

    async def _handle_mutate_ingress(self, request):
        request_json = await request.json()
        start = time.time()
        response = {}
        if "metadata" not in request_json["request"]["object"]:
            patch = [{
                "op": "add",
                "path": "/metadata",
                "value": {"labels": {"controlled-by-rampart": "true"}}
            }]
        elif "labels" not in request_json["request"]["object"]["metadata"]:
            patch = [{
                "op": "add",
                "path": "/metadata/labels",
                "value": {"controlled-by-rampart": "true"}
            }]
        else:
            patch = [{
                "op": "add",
                "path": "/metadata/labels/controlled-by-rampart",
                "value": "true"
            }]
        patch_str = json.dumps(patch)
        response["patch"] = base64.b64encode(patch_str.encode()).decode()
        response["patchType"] = "JSONPatch"
        response["allowed"] = True
        response["uid"] = request_json["request"]["uid"]
        duration = time.time() - start
        LOG.info("%s %s %s: %s",
                 request_json["request"]["operation"],
                 request_json["request"]["namespace"],
                 "elapsed",
                 duration)
        return web.json_response({
            "apiVersion": "admission.k8s.io/v1",
            "kind": "AdmissionReview",
            "response": response,
        })


if __name__ == "__main__":
    logging.basicConfig()
    kubernetes.config.load_incluster_config()

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", type=str, default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--tls-crt", type=str)
    parser.add_argument("--tls-key", type=str)
    args = parser.parse_args()

    if args.tls_crt and args.tls_key:
        ssl_context = ssl.SSLContext()
        ssl_context.load_cert_chain(args.tls_crt, args.tls_key)
    else:
        ssl_context = None

    mutating_webhook = MutatingWebhook()
    mutating_webhook.run(args.host, args.port, ssl_context=ssl_context)
