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

import builtins
import logging


class Event:
    """
    Defines the event body used by handler functions.
    """
    def __init__(self, body, request=None):
        self.body = body

        if request:
            self.headers = request.headers
            self.app = request.app
            self.url = request.url
            self.base_url = request.base_url
            self.method = request.method
            self.query_params = request.query_params
            self.receive = request.receive
            self.state = request.state
            self.client = request.client
            self.cookies = request.cookies


class Context:
    """
    Context class for ASGI interface. The user can use this to store user data
    and logging functionality.
    """
    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        self.logger.addHandler(ch)
        self.user_data = {}


def _inject_context():
    builtins.context = Context()
