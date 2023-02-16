# Copyright 2023 Petuum, Inc. All Rights Reserved.

import logging

from .classes import GraphPhase


class GraphLogger(logging.LoggerAdapter):
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
