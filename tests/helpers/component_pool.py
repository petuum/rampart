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

import copy

from src.graph.objects.edge import PulsarFlow, PVFlow
from src.graph.objects.base_types import Metadata
from tests.helpers.constants import REGISTRY_URL
from tests.helpers.utils import nested_dict


_test_metadata = Metadata("testnamespace", "testname", "testuid")


def _volume_edge(flow_name=None, mount_path="/"):
    return nested_dict({
        "type": "volume",
        "flow": flow_name or "volume_flow",
        "config": nested_dict({
            "mountPath": mount_path
        })
    })


def _pulsar_edge(flow_name=None):
    return nested_dict({
        "type": "pulsar",
        "flow": flow_name or "pulsar_flow",
    })


flows = {"volume_flow": PVFlow("volume_flow", {"size": "1G"}, _test_metadata),
         "pulsar_flow": PulsarFlow("pulsar_flow", {}, _test_metadata)}


COMPONENT_YAML_TEMPLATE = nested_dict({
    "chart": nested_dict({
        "name": "some_chart",
        "version": "0.1.0",
        "repo": REGISTRY_URL,
    }),
    "inputs": nested_dict(),
    "outputs": nested_dict(),
    "values": nested_dict()
})

ANNOTATION_TEMPLATE = nested_dict({
    "inputs": [nested_dict({
        "name": "input1",
        "type": "volume",
    })],
    "outputs": [nested_dict({
        "name": "output1",
        "type": "pulsar"
    })]
})


# Annotations
d = ANNOTATION_TEMPLATE

annotations_schema_invalid = [
    'inputs\n- name: stave_sql_input\n  type: volume\n'
    'outputs:\n- name: stave_sql_output\n  type: volume\n',
    d.delete("inputs"),
    d.delete("outputs"),
    d.add_or_edit("inputs", [{"type": "volume"}]),
    d.add_or_edit("inputs", [{"name": "input1"}]),
    d.add_or_edit("outputs", [{"type": "pulsar"}]),
    d.add_or_edit("outputs", [{"name": "output1"}]),
    d.add_or_edit("inputs", [d["inputs"][0].add_or_edit("somethingIrrelevant", "")]),
    d.add_or_edit("outputs", [d["outputs"][0].add_or_edit("somethingIrrelevant", "")]),
    d.add_or_edit("somethingIrrelevant", ""),
    d.add_or_edit("inputs", [d["inputs"][0].add_or_edit("name", "not/valid")]),
    d.add_or_edit("outputs", [d["outputs"][0].add_or_edit("name", "not*valid")]),
    d.add_or_edit("inputs", [d["inputs"][0].add_or_edit("type", "notExist")]),
    d.add_or_edit("outputs", [d["outputs"][0].add_or_edit("type", "notExist")]),
    d.add_or_edit("inputs", [d["inputs"][0].add_or_edit("config", {"mountPath", "relative/path"})])
]

annotations_duplicate_io = [
    d.add_or_edit("inputs", d["inputs"] * 2),
    d.add_or_edit("outputs", d["outputs"] * 2)
]
annotations_conflict_io = [
    d.add_or_edit("inputs", d["inputs"] + [d["inputs"][0].add_or_edit("type", "pulsar")]),
    d.add_or_edit("inputs", d["outputs"] + [d["outputs"][0].add_or_edit("type", "volume")]),
    d.add_or_edit("inputs", [{"name": "input*", "type": "volume"}] * 2),
    d.add_or_edit("inputs", [{"name": "output*", "type": "pulsar"}] * 2),
]
annotations_overlap_io = [
    d.add_or_edit("inputs", [{"name": "input1", "type": "volume"},
                             {"name": "input*", "type": "pulsar"}]),
    d.add_or_edit("outputs", [{"name": "output1", "type": "pulsar"},
                              {"name": "output*", "type": "volume"}]),
    d.add_or_edit("inputs", [{"name": "input_x_*", "type": "volume"},
                             {"name": "input*", "type": "pulsar"}]),
    d.add_or_edit("outputs", [{"name": "output_x_*", "type": "pulsar"},
                              {"name": "output*", "type": "volume"}])
]

annotations_invalid_mount_path = [
    d.add_or_edit("inputs", [{"name": "input*", "type": "volume", "mountPath": "/input1"}]),
    d.add_or_edit("outputs", [{"name": "output*", "type": "volume", "mountPath": "/output1"}])
]

annotations_normal = [
    copy.deepcopy(d),
    d.add_or_edit("inputs", [{"name": "input*", "type": "volume"}]),
    d.add_or_edit("inputs", [{"name": "output*", "type": "pulsar"}]),
    d.add_or_edit("inputs", [{"name": "input*", "type": "volume", "mountPath": "/input*"}]).
    add_or_edit("outputs", [{"name": "output*", "type": "volume", "mountPath": "/output*"}]),
]


# Charts containing the annotations
charts_annotation_schema_invalid = {f"chart_annotation_schema_invalid_{i}": annotation
                                    for i, annotation in enumerate(annotations_schema_invalid)}
charts_annotation_duplicate_io = {f"chart_annotation_duplicate_io_{i}": annotation
                                  for i, annotation in enumerate(annotations_duplicate_io)}
charts_annotation_conflict_io = {f"chart_annotation_conflict_io_{i}": annotation
                                 for i, annotation in enumerate(annotations_conflict_io)}
charts_annotation_overlap_io = {f"chart_annotation_overlap_io_{i}": annotation
                                for i, annotation in enumerate(annotations_overlap_io)}
charts_annotation_invalid_mount_path = {f"chart_annotation_invalid_mount_path_{i}": annotation
                                        for i, annotation
                                        in enumerate(annotations_invalid_mount_path)}
charts_annotation_normal = {f"chart_annotation_normal_{i}": annotation
                            for i, annotation in enumerate(annotations_normal)}
all_charts = {**charts_annotation_schema_invalid, **charts_annotation_duplicate_io,
              **charts_annotation_conflict_io, **charts_annotation_overlap_io,
              **charts_annotation_invalid_mount_path, **charts_annotation_normal}


# Components using the charts
d = COMPONENT_YAML_TEMPLATE

annotation_schema_invalid = [
    d.add_or_edit("chart", {
        "name": chart_name,
        "version": "0.0.0",
        "repo": REGISTRY_URL
    }) for chart_name in charts_annotation_schema_invalid
]

annotation_duplicate_io = [
    d.add_or_edit("chart", {
        "name": chart_name,
        "version": "0.0.0",
        "repo": REGISTRY_URL
    }) for chart_name in charts_annotation_duplicate_io
]

annotation_conflict_io = [
    d.add_or_edit("chart", {
        "name": chart_name,
        "version": "0.0.0",
        "repo": REGISTRY_URL
    }) for chart_name in charts_annotation_conflict_io
]

annotation_overlap_io = [
    d.add_or_edit("chart", {
        "name": chart_name,
        "version": "0.0.0",
        "repo": REGISTRY_URL
    }) for chart_name in charts_annotation_overlap_io
]

annotation_invalid_mount_path = [
    d.add_or_edit("chart", {
        "name": chart_name,
        "version": "0.0.0",
        "repo": REGISTRY_URL
    }) for chart_name in charts_annotation_invalid_mount_path
]

annotation_normal = [
    d.add_or_edit("chart", {
        "name": chart_name,
        "version": "0.0.0",
        "repo": REGISTRY_URL
    }) for chart_name in charts_annotation_normal
]

# Complete component bodies
type_mismatch_with_spec = [
    annotation_overlap_io[0].add_or_edit("inputs", {"input1": _pulsar_edge()}),
    annotation_overlap_io[0].add_or_edit("inputs", {"input2": _volume_edge()}),
    annotation_overlap_io[1].add_or_edit("outputs", {"output1": _volume_edge()}),
    annotation_overlap_io[1].add_or_edit("outputs", {"output2": _pulsar_edge()}),
    annotation_overlap_io[2].add_or_edit("inputs", {"input_x_1": _pulsar_edge()}),
    annotation_overlap_io[2].add_or_edit("inputs", {"input_1": _volume_edge()}),
    annotation_overlap_io[3].add_or_edit("outputs", {"output_x_1": _volume_edge()}),
    annotation_overlap_io[3].add_or_edit("outputs", {"output_1": _pulsar_edge()}),
    annotation_normal[0].add_or_edit("inputs", {"input1": _pulsar_edge()}),
    annotation_normal[0].add_or_edit("outputs", {"output1": _volume_edge()}),
    annotation_normal[1].add_or_edit("inputs", {"input1": _pulsar_edge()}),
    annotation_normal[2].add_or_edit("outputs", {"output1": _volume_edge()})
]

type_mismatch_with_flow = [
    annotation_overlap_io[0].add_or_edit("inputs", {"input1": _volume_edge("pulsar_flow")}),
    annotation_overlap_io[0].add_or_edit("inputs", {"input2": _pulsar_edge("volume_flow")}),
    annotation_overlap_io[1].add_or_edit("outputs", {"output1": _pulsar_edge("volume_flow")}),
    annotation_overlap_io[1].add_or_edit("outputs", {"output2": _volume_edge("pulsar_flow")}),
    annotation_overlap_io[2].add_or_edit("inputs", {"input_x_1": _volume_edge("pulsar_flow")}),
    annotation_overlap_io[2].add_or_edit("inputs", {"input_1": _pulsar_edge("volume_flow")}),
    annotation_overlap_io[3].add_or_edit("outputs", {"output_x_1": _pulsar_edge("volume_flow")}),
    annotation_overlap_io[3].add_or_edit("outputs", {"output_1": _volume_edge("pulsar_flow")}),
    annotation_normal[0].add_or_edit("inputs", {"input1": _volume_edge("pulsar_flow")}),
    annotation_normal[0].add_or_edit("outputs", {"output1": _pulsar_edge("volume_flow")}),
    annotation_normal[1].add_or_edit("inputs", {"input1": _volume_edge("pulsar_flow")}),
    annotation_normal[2].add_or_edit("outputs", {"output1": _pulsar_edge("volume_flow")})
]

bad_flow_reference = [
    annotation_normal[0].add_or_edit("inputs", {"input1": _volume_edge("not_exist")}),
    annotation_normal[0].add_or_edit("outputs", {"output1": _pulsar_edge("not_exist")}),
    annotation_normal[1].add_or_edit("inputs", {"input1": _volume_edge("not_exist")}),
    annotation_normal[2].add_or_edit("outputs", {"output1": _pulsar_edge("not_exist")})
]

overlap_mount_path = [
    annotation_normal[1].add_or_edit("inputs", {"input1": _volume_edge(mount_path="/a"),
                                                "input2": _volume_edge(mount_path="/a/b")}),
    annotation_normal[1].add_or_edit("inputs", {"input1": _volume_edge(mount_path="/"),
                                                "input2": _volume_edge(mount_path="/a/b")}),
    annotation_normal[1].add_or_edit("inputs", {"input1": _volume_edge(mount_path="/a/b/"),
                                                "input2": _volume_edge(mount_path="/a/b")}),
]

invalid_default_mount_path = [
    annotation_invalid_mount_path[0].add_or_edit("inputs", {"input1": _volume_edge()})
]

normal = [
    annotation_overlap_io[0].add_or_edit("inputs", {"input1": _volume_edge()}),
    annotation_overlap_io[0].add_or_edit("inputs", {"input2": _pulsar_edge()}),
    annotation_overlap_io[1].add_or_edit("outputs", {"output1": _pulsar_edge()}),
    annotation_overlap_io[1].add_or_edit("outputs", {"output2": _volume_edge()}),
    annotation_overlap_io[2].add_or_edit("inputs", {"input_x_1": _volume_edge()}),
    annotation_overlap_io[2].add_or_edit("inputs", {"input_1": _pulsar_edge()}),
    annotation_overlap_io[3].add_or_edit("outputs", {"output_x_1": _pulsar_edge()}),
    annotation_overlap_io[3].add_or_edit("outputs", {"output_1": _volume_edge()}),
    annotation_normal[0].add_or_edit("inputs", {"input1": _volume_edge()}),
    annotation_normal[0].add_or_edit("outputs", {"output1": _pulsar_edge()}),
    annotation_normal[1].add_or_edit("inputs", {"input1": _volume_edge()}),
    annotation_normal[2].add_or_edit("outputs", {"output1": _pulsar_edge()}),
    annotation_normal[3].add_or_edit("inputs", {"input1": _volume_edge(mount_path="")})
                        .add_or_edit("outputs", {"output1": _volume_edge(mount_path="/some/path")}),
]

default_mount_path = [
    annotation_normal[0].add_or_edit("inputs", {"input1": _volume_edge()}),
    annotation_normal[0].add_or_edit("inputs", {"input1": _volume_edge(mount_path="")}),
    annotation_normal[1].add_or_edit("inputs", {"input1": _volume_edge()}),
    annotation_normal[1].add_or_edit("inputs", {"input1": _volume_edge(mount_path="")}),
    annotation_normal[3].add_or_edit("inputs", {"input1": _volume_edge(mount_path="")})
                        .add_or_edit("outputs", {"output1": _volume_edge(mount_path="/some/path")}),
    annotation_normal[3].add_or_edit("inputs", {"no_match_in": _volume_edge(mount_path="")})
    .add_or_edit("outputs", {"no_match_out": _volume_edge(mount_path="/some/path")}),
]
