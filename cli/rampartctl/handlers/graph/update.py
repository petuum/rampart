# Copyright 2023 Petuum, Inc. All Rights Reserved.
import kubernetes
import sys

from .utils import merge_values

import yaml
try:
    from yaml import CSafeLoader as Loader, CSafeDumper as Dumper
except ImportError:
    from yaml import SafeLoader as Loader, SafeDumper as Dumper # noqa: 401


def handle_update_graph(args, remaining, help_fn):
    api = kubernetes.client.CustomObjectsApi()

    if args.filename:
        with open(args.filename, "rb") as f:
            graph = yaml.safe_load(f)
    else:
        graph = None

    if not args.namespace:
        if "namespace" not in graph["metadata"]:
            namespace = "default"
        else:
            namespace = graph["metadata"]["namespace"]
    else:
        namespace = args.namespace

    if not args.name:
        if not graph:
            print("If no graph yaml file is provided, you must provide the graph name.")
            exit(1)
        if "name" not in graph["metadata"]:
            print(f"An explicit name field is not found in {args.filename}. "
                  "metadata.generateName will not suffice for updating an existing graph.")
            exit(1)
        else:
            name = graph["metadata"]["name"]
    else:
        name = args.name

    namespace_api = kubernetes.client.CoreV1Api()
    namespaces = namespace_api.list_namespace()
    namespaces = namespaces.items

    if namespace not in [namespace.metadata.name for namespace in namespaces]:
        print(f"Namespace {args.namespace} does not exist")
        sys.exit(1)

    try:
        deployed_yaml = api.get_namespaced_custom_object(
            "rampart.petuum.com", "v1beta1", namespace, "rampartgraphs", name)
    except kubernetes.client.exceptions.ApiException as e:
        if e.status == 404 and "Not Found" in str(e.reason):
            print(f"Rampart graph {args.namespace}/{args.name} not found. Aborting.")
            sys.exit(1)
        raise e

    if not graph:
        graph = deployed_yaml

    version = deployed_yaml["metadata"]["resourceVersion"]
    graph["metadata"]["resourceVersion"] = version
    graph["metadata"]["name"] = name

    try:
        merge_values(graph, args.filename, args.values)
    except RuntimeError as e:
        print(str(e))
        exit(1)

    result = api.replace_namespaced_custom_object(
        "rampart.petuum.com", "v1beta1", namespace, "rampartgraphs", name, graph)
    print("Rampart graph updated: ")
    print(f"\tNamespace: {result['metadata']['namespace']}")
    print(f"\tName: {result['metadata']['name']}")
    print(f"\tUID: {result['metadata']['uid']}")


def register_update_graph(subparsers):
    parser_update = subparsers.add_parser(
        "update", help="update a rampart graph")
    parser_update.add_argument(
        "name", default="", type=str, nargs="?",
        help=("Optional. Overwrites any name specification provided in --filename"))
    parser_update.add_argument(
        "-f", "--filename", default="", type=str, help="path to the rampart graph file")
    parser_update.add_argument(
        "-n", "--namespace", type=str, default="",
        help=("Optional. Overwrites any namespace specification provided in --filename. "
              "Defaults to \"default\" if both this argument and the namespace in the file "
              "are left unspecified."))
    parser_update.add_argument(
        "-v", "--values", action="append",
        help=(
            "A mapping of the form <values_file>, <url>,"
            " <component_name>=<values_file> or <component_name>=<url>."
            " Can specify multiple values. Paths without the component_name "
            " are applied globally. Later values take precedence."))
    parser_update.set_defaults(handler=handle_update_graph)
