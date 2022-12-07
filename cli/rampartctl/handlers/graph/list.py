# Copyright 2023 Petuum, Inc. All Rights Reserved.

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
