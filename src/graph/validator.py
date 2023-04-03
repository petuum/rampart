# Copyright 2023 Petuum, Inc. All Rights Reserved.

import argparse
import asyncio
import logging
import ssl

import kubernetes_asyncio as kubernetes

from aiohttp import web
from http import HTTPStatus

from .constants import INFRA_LOCK_TIMEOUT, RAMPART_CRD_API
from .objects.base_types import Metadata
from .objects.graph import Graph
from .repository import get_global_repo_manager
from .utils.classes import ValidationError

LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)

"""
This module acts as an validating admission webhook:
https://kubernetes.io/docs/reference/access-authn-authz/admission-controllers/#validatingadmissionwebhook

and as a conversion webhook:
https://kubernetes.io/docs/tasks/extend-kubernetes/custom-resources/custom-resource-definition-versioning/

The validator exposes three endpoints:

/healthz: returns the status of the validator
/validate: returns whether the graph yaml is valid
/conversion: converts between different RampartGraph custom resource versions.
             Fields/features that are missing in older versions may get default values in the
             newer versions.
"""


class Validator(object):
    def __init__(self):
        self._app = web.Application()
        self._app.add_routes([
            web.get('/healthz', self._handle_healthz),
            web.post('/validate', self._handle_validate),
            # TODO: move this to a different file
            web.post('/conversion', self._handle_conversion),
        ])
        self._infra_lock = asyncio.Lock()

    def get_app(self):
        return self._app

    def run(self, host, port, ssl_context=None):
        web.run_app(self.get_app(), host=host, port=port,
                    ssl_context=ssl_context)

    async def _handle_healthz(self, request):
        # Health check.
        return web.Response()

    async def _handle_validate(self, request):
        request_json = await request.json()
        request = request_json["request"]
        if ("name" not in request and "generateName" not in request):
            response = {
                "allowed": False,
                "status": {
                    "code": HTTPStatus.FORBIDDEN,
                    "reason": "Invalid graph",
                    "message": "No name found"
                }
            }
        else:
            metadata = Metadata(
                request.get("namespace", "default"),
                request.get("name", request.get("generateName")),
                request["uid"])
            generated_name = "name" not in request_json["request"]
            if request["operation"] == "CREATE":
                response = await self._validate(request, metadata, generated_name)
            elif request["operation"] == "UPDATE":
                response = await self._validate(request, metadata, generated_name)
            else:
                response = {"allowed": True}
            LOG.info("%s %s/%s: %s",
                     request["operation"],
                     request["namespace"],
                     str(metadata),
                     response)
        response["uid"] = request["uid"]
        return web.json_response({
            "apiVersion": "admission.k8s.io/v1",
            "kind": "AdmissionReview",
            "response": response,
        })

    async def _validate(self, request, metadata, generated_name):
        graph = request["object"]

        # Graph is marked for deletion, no need to validate (otherwise there is no way to delete
        # invalid graphs)
        if "deletionTimestamp" in graph["metadata"]:
            return {"allowed": True}
        try:
            graph = await Graph.from_json(graph["spec"], metadata, validate_specs=False)

            try:
                await asyncio.wait_for(self._infra_lock.acquire(), INFRA_LOCK_TIMEOUT)
            except asyncio.TimeoutError:
                raise ValidationError({
                    "Timeout waiting for another graph to validate. This is a transient error. "
                    "Please try again."})
            try:
                await get_global_repo_manager().update_provides()
                await graph.validate(validate_specs=False)
            finally:
                self._infra_lock.release()
            return {"allowed": True}

        except ValidationError as e:
            return {"allowed": False,
                    "status": {
                        "code": HTTPStatus.FORBIDDEN,
                        "reason": "Invalid: " + "\n".join(e.errors),
                        "message": "\n".join(e.errors)
                    }
                    }

    async def _handle_conversion(self, request):
        """
        Currently there are two versions `v1beta1` and `v1beta2`. The only difference between
        the two is that `v1beta2` adds a field `spec.deploy`: boolean, which specifies if
        we want the graph to actually be deployed. Setting it to false will undeploy everything,
        but leave the CR.

        Converting to `v1beta2` from `v1beta1` will just add `spec.deploy: True`
        `v1beta1` cannot fully represent `v1beta2` graphs.
        """

        request_json = await request.json()
        request_version = request_json["apiVersion"]
        request = request_json["request"]
        desired_api = request["desiredAPIVersion"]
        desired_version = desired_api.split("/")[-1]
        converted_objects = []
        for obj in request["objects"]:
            LOG.info(f'{obj["apiVersion"]}, {obj["apiVersion"].split("/")[-1]}')
            if obj["apiVersion"].split("/")[-1] == "v1beta1":
                if desired_version == "v1beta2":
                    obj["spec"]["deploy"] = True
            elif obj["apiVersion"] == RAMPART_CRD_API:
                if desired_version == "v1beta1" and "deploy" in obj["spec"]:
                    del obj["spec"]["deploy"]
            obj["apiVersion"] = desired_api
            converted_objects += [obj]

        response = {
            "uid": request["uid"],
            "result": {
                "status": "Success",
            },
            "convertedObjects": converted_objects}

        return web.json_response({
            "apiVersion": request_version,
            "kind": "ConversionReview",
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

    validator = Validator()
    validator.run(args.host, args.port, ssl_context=ssl_context)
