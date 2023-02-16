# Copyright 2023 Petuum, Inc. All Rights Reserved.

import os
import pytest

from run_test import run_test
from graph_generator import simple, complete, bipartite  # noqa: 401


@pytest.mark.parametrize("namespace", "default")
@pytest.mark.parametrize(("name", "graph"), [("test-simple", "simple()"),
                                             ("k_2,4", "bipartite(2,4)"),
                                             ("k_6,8", "bipartite(6,8)"),
                                             ("k_10,20", "bipartite(10,20)"),
                                             ("k_10", "complete(10,3,2,4)")])
def test_end_to_end(namespace, name, graph):
    if os.environ.get("KUBERNETES_SERVICE_HOST", ""):
        return run_test(namespace, name, eval(graph), incluster=True)
    else:
        return run_test(namespace, name, eval(graph), incluster=False)
