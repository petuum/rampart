# Copyright 2023 Petuum, Inc. All Rights Reserved.
import copy

from tests.helpers.constants import REGISTRY_URL
from tests.helpers.utils import nested_dict

GRAPH_YAML_TEMPLATE = nested_dict({
    "graph": nested_dict({
        "components": nested_dict({
            "component1": nested_dict({
                "chart": nested_dict({
                    "name": "test_helm_valid_a",
                    "version": "0.1.0",
                    "repo": REGISTRY_URL
                }),
                "inputs": nested_dict({
                    "input1": nested_dict({
                        "type": "volume",
                        "flow": "flow1",
                        "config": nested_dict({
                            "mountPath": "/input1"}),
                        "$ui": nested_dict()
                    }),
                    "input2": nested_dict({
                        "type": "repository",
                        "flow": "flow3",
                        "config": nested_dict({
                            "mountPath": "/input2"}),
                        "$ui": nested_dict()
                    })
                }),
                "outputs": nested_dict({
                    "output1": nested_dict({
                        "type": "pulsar",
                        "flow": "flow2",
                        "config": nested_dict(),
                        "$ui": nested_dict()
                    })
                }),
                "config": nested_dict(),
                "type": "some_type",
                "$ui": nested_dict()
            }),
        }),
        "flows": nested_dict({
            "flow1": nested_dict({
                "type": "volume",
                "config": nested_dict({
                    "size": "1G"
                }),
                "$ui": nested_dict()
            }),
            "flow2": nested_dict({
                "type": "pulsar",
                "config": nested_dict({}),
                "$ui": nested_dict()
            }),
            "flow3": nested_dict({
                "type": "repository",
                "config": nested_dict({
                    "kind": "git",
                    "size": "1G"
                }),
                "$ui": nested_dict()
            }),
            "flow4": nested_dict({
                "type": "repository",
                "config": nested_dict({
                    "kind": "dvc",
                    "size": "1G"
                }),
                "$ui": nested_dict()
            })
        })
    })
})
d = GRAPH_YAML_TEMPLATE
schema_invalid = [
    # missing graph-level keys
    d.delete("graph"),
    d.delete("graph.components"),
    d.delete("graph.flows"),
    # unexpected top-level keys
    d.add_or_edit("graph.somethingIrrelevant", ""),
    # missing component-level keys
    d.delete("graph.components.component1.chart"),
    d.delete("graph.components.component1.inputs"),
    d.delete("graph.components.component1.outputs"),
    d.delete("graph.components.component1.config"),
    # unexpected component-level keys
    d.add_or_edit("graph.components.component1.somethingIrrelevant", ""),
    # missing chart-level keys
    d.delete("graph.components.component1.chart.name"),
    d.delete("graph.components.component1.chart.repo"),
    # unexpected chart-level keys
    d.add_or_edit("graph.components.component1.chart.somethingIrrelevant", ""),
    # missing component I/O keys
    d.delete("graph.components.component1.inputs.input1.flow"),
    d.delete("graph.components.component1.inputs.input1.type"),
    d.delete("graph.components.component1.outputs.output1.type"),
    d.delete("graph.components.component1.outputs.output1.flow"),
    # unexpected component I/O keys
    d.add_or_edit("graph.components.component1.inputs.input1.somethingIrrelevant", ""),
    d.add_or_edit("graph.components.component1.inputs.input1.config.somethingIrrelevant", ""),
    d.add_or_edit("graph.components.component1.outputs.output1.somethingIrrelevant", ""),
    # invalid I/O name
    d.add_or_edit("graph.components.component1.inputs.invalid/input/name",
                  copy.deepcopy(d["graph"]["components"]["component1"]["inputs"]["input1"])),
    d.add_or_edit("graph.components.component1.outputs.invalid/output/name",
                  copy.deepcopy(d["graph"]["components"]["component1"]["outputs"]["output1"])),
    # missing flow-level keys
    d.delete("graph.flows.flow1.type"),
    d.delete("graph.flows.flow1.config"),
    d.delete("graph.flows.flow1.config.size"),
    d.delete("graph.flows.flow2.type"),
    d.delete("graph.flows.flow3.config.kind"),
    d.delete("graph.flows.flow3.config.size"),
    d.delete("graph.flows.flow4.config.kind"),
    d.delete("graph.flows.flow4.config.size"),
    # unexpected flow-level keys
    d.add_or_edit("graph.flows.flow1.somethingIrrelevant", ""),
    d.add_or_edit("graph.flows.flow1.config.somethingIrrelevant", ""),
    d.add_or_edit("graph.flows.flow1.config.reclaimPolicy", "invalid"),
    d.add_or_edit("graph.flows.flow2.somethingIrrelevant", ""),
    # invalid flow name
    d.add_or_edit("graph.flows.invalid/flow/name", copy.deepcopy(d["graph"]["flows"]["flow1"])),
    # invalid repository config kind
    d.add_or_edit("graph.flows.flow3.config.kind", "invalid_kind"),
]


component_annotation_invalid = []
for name, version in zip(["test_helm_invalid_a"] * 3 + ["test_helm_invalid_b"],
                         ["0.1.0", "0.2.0", "0.3.0", "0.10.0"]):
    component_annotation_invalid.append(
        d.add_or_edit("graph.components.component1.chart", {
            "name": name,
            "version": version,
            "repo": REGISTRY_URL
        })
    )

# the rest of graphs should pass all schema checks
flow_optional_values = [
    d.add_or_edit("graph.flows.flow1.config.reclaimPolicy", "Retain"),
    d.add_or_edit("graph.flows.flow1.config.reclaimPolicy", "Delete")
]
component_optional_values = [
    d.delete("graph.components.component1.inputs.input1.config"),
    d.delete("graph.components.component1.inputs.input1.config.mountPath")
]

component_config_invalid = [
    d.add_or_edit("graph.components.component1.inputs.input1.flow", "not-exist"),
    d.add_or_edit("graph.components.component1.inputs.input1.type", "pulsar"),
    d.add_or_edit("graph.components.component1.inputs.input2.config", {"mountPath": "/input1/bad"}),
    d.delete("graph.components.component1.inputs.input1.config"),
    d.add_or_edit("graph.components.component1.outputs.output1.flow", "not-exist"),
    d.add_or_edit("graph.components.component1.outputs.output1.type", "volume"),
    d.add_or_edit("graph.components.component1.outputs.output1.config", {"mountPath": "/"}),
]

_component = GRAPH_YAML_TEMPLATE["graph"]["components"]["component1"]

component_validation_error = [
    d.add_or_edit("graph.components.flow1", copy.deepcopy(_component)),
]

multiple_components = [
    d.add_or_edit("graph.components.component2", copy.deepcopy(_component)),
    d.add_or_edit("graph.components.component2", _component.add_or_edit("chart.version", "0.2.0")),
    d.add_or_edit("graph.components.component2", _component.add_or_edit("chart.name", "different")),
    d.add_or_edit("graph.components.component2", _component.add_or_edit("chart.repo", "different")),
]
