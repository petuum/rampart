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

import unittest.mock

import kubernetes_asyncio as kubernetes
import pytest
import tests.helpers.graph_pool as graph_pool
import tests.src.graph.objects._test_graph_helper as helper

# The following patches are not needed because `conftest.py` was executed first and already
# used them to import the graph module. Putting them here anyways to be explicit.
with unittest.mock.patch.object(kubernetes, "client", unittest.mock.MagicMock()):
    with unittest.mock.patch.object(kubernetes, "config", unittest.mock.MagicMock()):
        from src.graph.objects.graph import Graph, Metadata, core_api, custom_api
        items_return = unittest.mock.MagicMock()
        items_return.items = [helper.generate_namespace("test1"),
                              helper.generate_namespace("test2"),
                              helper.generate_namespace("default-test-graph-2-c2")]
        core_api.list_namespace = unittest.mock.AsyncMock(return_value=items_return)
        custom_api.list_namespaced_custom_object = unittest.mock.AsyncMock(
            return_value={"items": helper.generate_rampart_graphs()})
        custom_api.list_cluster_custom_object = unittest.mock.AsyncMock(
            return_value={"items": helper.generate_rampart_graphs()})

from src.graph.utils.classes import ValidationError

import pprint


@pytest.fixture(scope="module")
def graph_metadata():
    return Metadata("testnamespace", "testname", "testuid")


@pytest.mark.asyncio
@pytest.mark.parametrize("graph_yaml", graph_pool.schema_invalid)
async def test_from_json_schema_error(graph_yaml, graph_metadata):
    pprint.pprint(graph_yaml)
    with pytest.raises(ValidationError):
        await Graph.from_json(graph_yaml, graph_metadata)


@pytest.mark.asyncio
@pytest.mark.parametrize("graph_yaml", graph_pool.component_annotation_invalid
                         + graph_pool.component_config_invalid + graph_pool.flow_optional_values
                         + graph_pool.component_optional_values)
async def test_from_json_no_error(graph_yaml, graph_metadata):
    """Graphs that may be invalid but would not cause error in this method"""
    pprint.pprint(graph_yaml)
    graph = await Graph.from_json(graph_yaml, graph_metadata)
    assert graph._components.keys() == graph_yaml["graph"]["components"].keys()
    # there will be the hidden aux-chart added by default
    assert len(graph._component_charts) == len(graph_yaml["graph"]["components"])
    assert graph._flows.keys() == graph_yaml["graph"]["flows"].keys()


@pytest.mark.asyncio
@pytest.mark.parametrize("graph_yaml", graph_pool.component_validation_error)
async def test_from_json_validation_error(graph_yaml, graph_metadata):
    """Graphs that may be invalid but would not cause error in this method"""
    pprint.pprint(graph_yaml)
    graph = await Graph.from_json(graph_yaml, graph_metadata)
    with pytest.raises(ValidationError):
        await graph.validate(validate_specs=False)
    with pytest.raises(ValidationError):
        await graph.validate(validate_specs=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(("graph_yaml", "distinct_charts"), zip(graph_pool.multiple_components,
                                                                [1, 2, 2]))
async def test_from_json_multiple_components(graph_yaml, distinct_charts, graph_metadata):
    """Multiple components, some reference to the same charts."""
    graph_yaml["graph"]["components"]["component1"]["namespace"] = "test1"
    pprint.pprint(graph_yaml)

    with pytest.raises(ValidationError):
        await Graph.from_json(graph_yaml, graph_metadata)

    graph_yaml["graph"]["components"]["component1"]["namespace"] = "default-test-graph-2-c2"
    pprint.pprint(graph_yaml)

    with pytest.raises(ValidationError):
        await Graph.from_json(graph_yaml, graph_metadata)

    graph_yaml["graph"]["components"]["component1"]["namespace"] = "test2"
    pprint.pprint(graph_yaml)

    graph = await Graph.from_json(graph_yaml, graph_metadata)
    assert graph._components.keys() == graph_yaml["graph"]["components"].keys()
    # there will be hidden aux-chart added by default
    assert len(graph._component_charts) == distinct_charts
    assert graph._flows.keys() == graph_yaml["graph"]["flows"].keys()
    await graph.validate(validate_specs=False)
    await graph.validate(validate_specs=True)

# TODO: test initialize and validate with mocks
