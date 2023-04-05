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

import logging

from .classes import GraphPhase


class GraphLogger(logging.LoggerAdapter):
    """provides logging with Rampart specific information (graph metadata, phase, etc)"""
    def process(self, msg, kwargs):
        if self.extra["metadata"]:
            metadata = self.extra["metadata"]
            namespace = metadata.namespace.kubernetes_view
            name = metadata.name.kubernetes_view
        else:
            namespace = "None"
            name = "None"
        if "extra" in kwargs:
            phase = kwargs["extra"].get("phase", GraphPhase.NONE)
        else:
            phase = GraphPhase.NONE

        msg = f'graph_namespace={namespace} graph_name={name} phase={phase} : message="{msg}"'

        return msg, kwargs
