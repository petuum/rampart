# Copyright 2023 Petuum, Inc. All Rights Reserved.

from .utils import get_all_infras


def handle_list_graph(args, remaining, help_fn):
    if not args.namespace:
        args.all_namespaces = True
    infra_components = get_all_infras(args)
    for infra_component in infra_components:
        if "status" in infra_component:
            status_list = infra_component["status"]["provides"]
            status = {status_obj["name"]: {"source": status_obj["source"],
                                           "status": status_obj["status"]}
                      for status_obj in status_list}
        else:
            status = {}
        for provides in infra_component["spec"]["provides"]:
            name = provides["name"]
            if name in status:
                status_obj = status[name]
                print(f"{name} from "
                      f"{status_obj['source']['namespace']}: {status_obj['source']['name']}"
                      "\t\t"
                      f"status: {status_obj['status']}")
            else:
                print(f"{status_obj['name']} from an unknown graph"
                      "\t\tstatus: registered")


def register_list_infra(subparsers):
    parser_list = subparsers.add_parser(
        "list", help="list all rampart infrastructure component")
    namespace = parser_list.add_mutually_exclusive_group(required=False)
    namespace.add_argument(
        "-n", "--namespace", type=str, default=None,
        help="namespace to restrict the rampart graphs listed. Defaults to all namespaces")
    namespace.add_argument(
        "-A", "--all-namespaces", action='store_true',
        help="list across all namespaces, overrides `--namespace`")
    parser_list.set_defaults(handler=handle_list_graph)
