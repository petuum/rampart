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
import sys

from .utils import get_all_graphs


def handle_delete_graph(args, remaining, help_fn):
    api = kubernetes.client.CustomObjectsApi()

    if args.all:
        graphs = get_all_graphs(args)
        if not graphs:
            print("No graphs found. Exiting")
            return

    elif args.name:
        try:
            api.get_namespaced_custom_object(
                "rampart.petuum.com", "v1beta1", args.namespace, "rampartgraphs", args.name)
        except kubernetes.client.exceptions.ApiException as e:
            if e.status == 404 and "Not Found" in str(e.reason):
                print(f"Rampart graph {args.namespace}/{args.name} not found. Aborting.")
                sys.exit(1)
            raise e
        graphs = [{"metadata": {"namespace": args.namespace, "name": args.name}}]

    else:
        print("You must either specify a graph by name or use the --all flag. Aborting")
        exit(1)

    if not args.yes:
        print(f"You are about to delete the following graph{'s' if len(graphs) > 1 else ''}:")
        for graph in graphs:
            print(f"\t{graph['metadata']['namespace']}:\t {graph['metadata']['name']}")

        text = input("Do you want to continue? [y/N]")
        if not text or not text.lower()[0] == "y":
            print("Aborting.")
            sys.exit(0)

    for graph in graphs:
        api.delete_namespaced_custom_object(
            "rampart.petuum.com", "v1beta1", graph["metadata"]["namespace"],
            "rampartgraphs", graph["metadata"]["name"], async_req=True)
        print(f"Deleting {graph['metadata']['namespace']}/{graph['metadata']['name']}")


def register_delete_graph(subparsers):
    parser_delete = subparsers.add_parser(
        "delete", help="update a rampart graph")
    name = parser_delete.add_mutually_exclusive_group(required=True)
    name.add_argument(
        "name", type=str, nargs="?", help="name of the rampart graph to delete")
    name.add_argument(
        "-a", "--all", action='store_true',
        help="delete all rampart graphs in a namespace")
    namespace = parser_delete.add_mutually_exclusive_group(required=False)
    namespace.add_argument(
        "-n", "--namespace", type=str, default="default",
        help="namespace of the rampart graph to delete")
    namespace.add_argument(
        "-A", "--all-namespaces", action='store_true',
        help="delete across all namespaces, only available when using --all")
    parser_delete.add_argument(
        "-y", "--yes", action="store_true",
        help="pre-approve all confirmation messages")
    parser_delete.set_defaults(handler=handle_delete_graph)
