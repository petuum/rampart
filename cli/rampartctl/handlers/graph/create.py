# Copyright 2023 Petuum, Inc. All Rights Reserved.
import kubernetes

from .utils import merge_values

import yaml
try:
    from yaml import CSafeLoader as Loader, CSafeDumper as Dumper
except ImportError:
    from yaml import SafeLoader as Loader, SafeDumper as Dumper # noqa: 401


def handle_create_graph(args, remaining, help_fn):
    graph_filename = args.filename
    with open(graph_filename, "rb") as f:
        graph = yaml.safe_load(f)

    try:
        merge_values(graph, graph_filename, args.values)
    except RuntimeError as e:
        print(str(e))
        exit(1)

    api = kubernetes.client.CustomObjectsApi()

    namespace = None

    if args.namespace:
        namespace = args.namespace
    if "namespace" in graph["metadata"]:
        if namespace != graph["metadata"]["namespace"]:
            raise RuntimeError(f"User specified namespace {namespace} does not match "
                               f"namespace specified by graph file "
                               f"{graph['metadata']['namespace']}")
        else:
            namespace = graph["metadata"]["namespace"]

    result = api.create_namespaced_custom_object(
        "rampart.petuum.com", "v1beta1", namespace, "rampartgraphs", graph)
    print("Rampart graph created: ")
    print(f"\tNamespace: {result['metadata']['namespace']}")
    print(f"\tName: {result['metadata']['name']}")
    print(f"\tUID: {result['metadata']['uid']}")


def register_create_graph(subparsers):
    parser_create = subparsers.add_parser(
        "create", help="deploy a rampart graph")
    parser_create.add_argument(
        "-f", "--filename", required=True, type=str, help="path to the rampart graph file")
    parser_create.add_argument(
        "-n", "--namespace", type=str, default="default",
        help="namespace to deploy the rampart graph object in")
    parser_create.add_argument(
        "-v", "--values", action="append",
        help=(
            "A mapping of the form <values_file>, <url>,"
            " <component_name>=<values_file> or <component_name>=<url>."
            " Can specify multiple values. Paths without the component_name "
            " are applied globally. Later values take precedence."))
    parser_create.set_defaults(handler=handle_create_graph)
