# Copyright 2023 Petuum, Inc. All Rights Reserved.

import argparse
import kubernetes
import os

import yaml
try:
    from yaml import CSafeLoader as Loader, CSafeDumper as Dumper
except ImportError:
    from yaml import SafeLoader as Loader, SafeDumper as Dumper # noqa: 401

from rampartctl.handlers.graph.create import register_create_graph
from rampartctl.handlers.graph.delete import register_delete_graph
from rampartctl.handlers.graph.describe import register_describe_graph
from rampartctl.handlers.graph.edit import register_edit_graph
from rampartctl.handlers.graph.list import register_list_graph
from rampartctl.handlers.graph.update import register_update_graph

from rampartctl.handlers.infra.list import register_list_infra

from rampartctl.handlers.component.list import register_list_components

from rampartctl.handlers.ingress.list import register_list_ingress


def run():
    parser = argparse.ArgumentParser()
    parser.set_defaults(handler=lambda args, remaining, print_help: print_help())

    parser.add_argument(
        "--context", default="", type=str,
        help="Kubernetes context to use")
    subparsers = parser.add_subparsers(help="sub-command help")

    graph_parser = subparsers.add_parser("graph", help="commands to interact with Rampart Graphs")
    graph_subparsers = graph_parser.add_subparsers(help="sub-command help")

    infra_parser = subparsers.add_parser(
        "infra", help="commands to interact with Rampart Infra Components")
    infra_subparsers = infra_parser.add_subparsers(help="sub-command help")

    register_create_graph(graph_subparsers)
    register_delete_graph(graph_subparsers)
    register_describe_graph(graph_subparsers)
    register_edit_graph(graph_subparsers)
    register_list_graph(graph_subparsers)
    register_update_graph(graph_subparsers)

    register_list_infra(infra_subparsers)

    register_list_components(subparsers)

    register_list_ingress(subparsers)

    args, remaining = parser.parse_known_args()

    default_path = os.path.expanduser("~/.kube/config")
    config_file = os.environ.get("KUBECONFIG", default_path)
    if not os.path.exists(config_file):
        print(f"KUBECONFIG path {config_file} does not point to a file. Aborting.")
        exit(1)

    if args.context:
        contexts, active_context = kubernetes.config.list_kube_config_contexts(config_file)
        if not contexts:
            print(f"Cannot find any contexts in KUBECONFIG file {config_file}. Aborting")
        contexts = {context["name"]: context for context in contexts}
        if args.context not in contexts:
            print(f"Cannot find context {args.context} in available contexts.")
            exit(1)
        context = args.context
    else:
        context = None

    kubernetes.config.load_kube_config(
        config_file=config_file, context=context)

    api_client = kubernetes.client.ApiregistrationV1Api()

    services = api_client.list_api_service(_preload_content=False)
    services = yaml.safe_load(services.data)

    found = False
    for service in services["items"]:
        if service["metadata"]["name"] == "v1beta1.rampart.petuum.com":
            found = True

    if not found:
        print("Rampart is not installed. Please install Rampart on your cluster before using "
              "rampartctl.")
        exit(1)

    args.handler(args, remaining, parser.print_help)


if __name__ == "__main__":
    run()
