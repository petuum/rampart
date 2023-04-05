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

from .utils import get_all_graphs


def handle_list_graph(args, remaining, help_fn):
    graphs = get_all_graphs(args)
    for graph in graphs:
        # TODO: print format better, add status
        print(f"{graph['metadata']['namespace']}:\t{graph['metadata']['name']}")


def register_list_graph(subparsers):
    parser_list = subparsers.add_parser(
        "list", help="list all rampart graphs")
    namespace = parser_list.add_mutually_exclusive_group(required=False)
    namespace.add_argument(
        "-n", "--namespace", type=str, default="default",
        help="namespace to restrict the rampart graphs listed")
    namespace.add_argument(
        "-A", "--all-namespaces", action='store_true',
        help="list across all namespaces, overrides `--namespace`")
    parser_list.set_defaults(handler=handle_list_graph)
