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
import unittest.mock

import kubernetes_asyncio as kubernetes
import pytest
with unittest.mock.patch.object(kubernetes, "client", unittest.mock.MagicMock()):
    with unittest.mock.patch.object(kubernetes, "config", unittest.mock.MagicMock()):
        from src.graph.objects.graph import Metadata
import tests.helpers.component_pool as comp_pool

from src.graph.constants import LOGGING_FORMAT
from src.graph.objects.component import ComponentInstance
from src.graph.objects.component_chart import ComponentChart
from src.graph.repository import ComponentRepo, _GLOBAL_REPO_MANAGER


logging.basicConfig(format=LOGGING_FORMAT)
LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)


METADATA = ("testnamespace", "testname", "testuid")


@pytest.fixture(autouse=True)
def mock_update_provides(mocker):
    async def update_provides():
        pass
    mocker.patch.object(_GLOBAL_REPO_MANAGER, "update_provides",
                        mocker.AsyncMock(side_effect=update_provides))
    mocker.patch.object(_GLOBAL_REPO_MANAGER, "_provided", {"pulsar": ""})


@pytest.fixture(autouse=True)
def mock_get_component_annotations(mocker):
    async def get_component_annotations(chart_name, _, logger):
        if chart_name in comp_pool.all_charts:
            chart = comp_pool.all_charts[chart_name]
            return chart if isinstance(chart, str) else chart.to_yaml()
        else:
            return {}
    mocker.patch.object(ComponentRepo, "get_component_annotations",
                        mocker.AsyncMock(side_effect=get_component_annotations))


@pytest.fixture
def run_chart_initialize():
    graph_metadata = Metadata(*METADATA)

    def run_initialize(components, return_exceptions=False):
        component_charts = []
        for component in components:
            component_charts.append(ComponentChart(
                component["chart"]["name"],
                component["chart"]["version"],
                component["chart"]["repo"],
                graph_metadata))
        return component_charts
    return run_initialize


@pytest.fixture
def run_inst_initialize():
    metadata = Metadata(*METADATA)

    def run_initialize(comps, comp_charts, return_exceptions=False):
        comp_instances = []
        for comp, chart in zip(comps, comp_charts):
            comp_inst = ComponentInstance(metadata, comp, metadata, chart, comp_pool.flows)
            comp_instances.append(comp_inst)
        return comp_instances
    return run_initialize
