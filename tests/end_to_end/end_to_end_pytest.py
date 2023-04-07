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
