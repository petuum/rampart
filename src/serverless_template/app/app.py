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
import importlib

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from starlette.requests import Request

from utils import Event, Context


def make_post_method(endpoint, handler, app, context):
    @app.post(endpoint)
    def post_function_template(body: dict, request: Request):
        try:
            event = Event(body, request)
            output = handler(context, event)
        except Exception as exc:
            return HTTPException(500, detail=str(exc))
        return JSONResponse(output)


class FastAPIApp:
    """
    Implements the application side of ASGI interface using a FastAPI app.
    """
    def __init__(self, handlers, endpoints):
        self.app = FastAPI()
        self.context = Context()
        self.post_methods = [make_post_method(e, h, self.app, self.context)
                             for e, h in zip(endpoints, handlers)]


def create_app():
    function_config = os.getenv('FUNC_CONFIG')
    assert function_config, "FUNC_CONFIG not set!"
    with open(function_config, 'r') as stream:
        try:
            function_config = yaml.safe_load(stream)
        except yaml.YAMLError as exc:
            print(exc)

    handlers = []
    endpoints = []
    for k, v in function_config['functions'].items():
        handler_name = v['handler']
        splits = handler_name.split(":")
        module_name = '.'.join(splits[:-1])
        function_name = splits[-1]
        handler = getattr(importlib.import_module(module_name), function_name)
        handlers.append(handler)
        endpoints.append("/rampserv/" + k)

    return FastAPIApp(handlers, endpoints)


fast_app = create_app()
app = fast_app.app
