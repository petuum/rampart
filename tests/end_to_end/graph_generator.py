# Copyright 2023 Petuum, Inc. All Rights Reserved.

import copy


class Graph:
    def __init__(self, num_comps, num_flows, flow_types, in_edges, out_edges):
        self._comps = list(range(num_comps))
        self._flows = list(range(num_flows))
        self._flow_types = flow_types
        self._in_edges = {component: [] for component in self._comps}
        for comp_index, flow_index in in_edges:
            self._in_edges[comp_index].append(flow_index)
        self._out_edges = {component: [] for component in self._comps}
        for comp_index, flow_index in out_edges:
            self._out_edges[comp_index].append(flow_index)

    def edges(self):
        out_edges_transposed = {}
        for component in self._comps:
            for index, flow in enumerate(self._out_edges[component]):
                if flow in out_edges_transposed:
                    out_edges_transposed[flow].add((component, index))
                else:
                    out_edges_transposed[flow] = {(component, index)}

        result = {}
        for component in self._comps:
            component_name = f"component{component}"
            volume_connections = {}
            repo_connections = {}
            pulsar_connections = {}
            for index, flow in enumerate(self._in_edges[component]):
                outputs = out_edges_transposed[flow]
                if self._flow_types[flow] == "volume":
                    dictionary = volume_connections
                elif self._flow_types[flow] == "repository":
                    dictionary = repo_connections
                elif self._flow_types[flow] == "pulsar":
                    dictionary = pulsar_connections
                in_edge = f"input_{self._flow_types[flow]}_{index}"
                if in_edge not in dictionary:
                    dictionary[in_edge] = []
                outputs = []
                for out_comp, out_index in out_edges_transposed[flow]:
                    out_edge = f"output_{self._flow_types[flow]}_{out_index}"
                    outputs.append([f"component{out_comp}", out_edge])
                dictionary[in_edge].extend(outputs)

            result[component_name] = (volume_connections, pulsar_connections, repo_connections)
        return result

    def to_yaml(self, name, namespace):
        result = {
            "apiVersion": "rampart.petuum.com/v1beta1",
            "kind": "RampartGraph",
            "metadata": {
                "name": name,
                "namespace": namespace,
            },
            "spec": {
                "graph": {
                    "components": {},
                    "flows": {}
                }
            }
        }
        for component_index in self._comps:
            chart = {
                "repo": "rampart-repo",
                "name": "rampart-test-component",
                "version": "1.1.2"}
            config = {
                "component_name": f"component{component_index}"
                }
            inputs = {}
            for (edge_index, flow_index) in enumerate(self._in_edges[component_index]):
                flow_type = self._flow_types[flow_index]
                if flow_type == "volume" or flow_type == "repository":
                    edge_config = {"mountPath": f"/input{edge_index}"}
                else:
                    edge_config = {}
                inputs[f"input-{flow_type}-{edge_index}"] = {
                     "type": flow_type,
                     "config": {} if edge_index % 2 == 0 else edge_config,
                     "flow": f"flow-{flow_index}"}
            outputs = {}
            for (edge_index, flow_index) in enumerate(self._out_edges[component_index]):
                flow_type = self._flow_types[flow_index]
                if flow_type == "volume" or flow_type == "repository":
                    edge_config = {"mountPath": f"/output{edge_index}"}
                else:
                    edge_config = {}
                outputs[f"output-{flow_type}-{edge_index}"] = {
                     "type": flow_type,
                     "config": {} if edge_index % 2 == 0 else edge_config,
                     "flow": f"flow-{flow_index}"}
            result["spec"]["graph"]["components"][f"component{component_index}"] = {
                "chart": chart,
                "config": config,
                "inputs": inputs,
                "outputs": outputs}
        for flow_index in self._flows:
            flow_type = self._flow_types[flow_index]
            if flow_type == "pulsar":
                flow = {
                    "type": "pulsar",
                    "config": {}
                }
            else:
                flow = {
                    "type": flow_type,
                    "config": {"size": "1G"}
                }
                if flow_type == "repository":
                    flow["config"]["kind"] = "git"
            result["spec"]["graph"]["flows"][f"flow-{flow_index}"] = flow
        return result


def bipartite(g1, g2):
    flows = ["volume", "volume", "repository", "repository", "pulsar", "pulsar"]
    edges_1_out = [(component, flow) for component in range(g1) for flow in range(0, 6, 2)]
    edges_1_in = [(component, flow) for component in range(g1) for flow in range(1, 6, 2)]
    edges_2_out = [(component + g1, flow) for component in range(g2) for flow in range(1, 6, 2)]
    edges_2_in = [(component + g1, flow) for component in range(g2) for flow in range(0, 6, 2)]
    return Graph(
        g1 + g2,
        len(flows), flows,
        edges_1_in + edges_2_in, edges_1_out + edges_2_out)


def complete(components, volume_flows, repo_flows, pulsar_flows):
    flows = volume_flows + repo_flows + pulsar_flows
    edges = [(component, flow) for component in range(components) for flow in range(flows)]
    return Graph(
        components,
        flows,
        ["volume" for _ in range(volume_flows)] +
        ["repository" for _ in range(repo_flows)] +
        ["pulsar" for _ in range(pulsar_flows)],
        edges, copy.deepcopy(edges))


def simple():
    return Graph(2, 2, ["volume", "pulsar"], [(0, 0), (0, 1)], [(1, 0), (1, 1)])
