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

import kubernetes
import yaml

from .utils import get_all_graphs


def handle_describe_graph(args, remaining, help_fn):
    graphs = get_all_graphs(args)
    # TODO: delay printing until the end, do each component asynchronously
    for i, graph in enumerate(graphs):
        if i != 0:
            print()
            # TODO: real number instead of 80
            print("-" * 80)
            print()

        if graph["metadata"]["name"].startswith(args.name):
            if args.verbose >= 0:
                print(f"namespace:\t{graph['metadata']['namespace']}")
                print(f"name:\t\t{graph['metadata']['name']}")
                if "status" not in graph:
                    print("generation:\t\t0")
                    print("status:\t\tNone")
                    print("components:\t\tNone")
                else:
                    if "observedGeneration" in graph["status"]:
                        print(f"generation:\t\t{graph['status']['observedGeneration']}")
                    if "phase" in graph["status"]:
                        print(f"status:\t\t{graph['status']['phase']}")
                    if graph["status"]["phase"] == "Failed":
                        reason = graph["status"]["reason"]
                        message = graph["status"]["messages"]
                        print(f"failure reason:\t\t{reason}")
                        if args.verbose >= 1:
                            print(f"failure message:\t\t{message}")
                    if "componentNamespaces" in graph['status']:
                        print("\ncomponents:")
                        for component in graph['status']['componentNamespaces']:
                            print(f"\t\t{component}")
            if (args.verbose >= 1
                    and "status" in graph and graph["status"].get("phase", None) == "Deployed"):
                print("\nflows:")
                flows = "\t" + yaml.dump(graph["spec"]["graph"]["flows"]).replace("\n", "\n\t")
                print(flows)
            if args.verbose >= 2:
                core_api = kubernetes.client.CoreV1Api()
                tasks = []
                if "componentNamespaces" in graph['status']:
                    for component in graph['status']['componentNamespaces']:
                        tasks.append(core_api.list_namespaced_pod(component, async_req=True))
                    print("pods:")
                    for task in tasks:
                        namespace_pods = task.get().items
                        for pod in namespace_pods:
                            print(f"\t{pod.metadata.namespace}"
                                  f"\t{pod.metadata.name}\t{pod.status.phase}")
            if args.verbose >= 3:
                if "managedFields" in graph["metadata"]:
                    del graph["metadata"]["managedFields"]
                graph_string = "\t" + yaml.dump(graph, indent=4).replace('\n', '\n\t')
                print("\ndescription:")
                print(graph_string)


def register_describe_graph(subparsers):
    parser_describe = subparsers.add_parser(
        "describe", help="describe all rampart graphs")
    parser_describe.add_argument(
        "name", nargs="?", type=str, default="",
        help="prefix of rampart graphs to describe")
    namespace = parser_describe.add_mutually_exclusive_group(required=False)
    namespace.add_argument(
        "-n", "--namespace", type=str, default="default",
        help="namespace to restrict the rampart graphs listed")
    namespace.add_argument(
        "-A", "--all-namespaces", action='store_true',
        help="list across all namespaces, overrides `--namespace`")
    parser_describe.add_argument(
        "-v", "--verbose", action='count', default=0)
    parser_describe.set_defaults(handler=handle_describe_graph)
