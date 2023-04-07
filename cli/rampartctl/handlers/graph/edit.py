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
import os
import sys
import tempfile

import yaml
try:
    from yaml import CSafeLoader as Loader, CSafeDumper as Dumper
except ImportError:
    from yaml import SafeLoader as Loader, SafeDumper as Dumper # noqa: 401


def handle_edit_graph(args, remaining, help_fn):
    api = kubernetes.client.CustomObjectsApi()

    name = args.name
    namespace = args.namespace

    namespace_api = kubernetes.client.CoreV1Api()
    namespaces = namespace_api.list_namespace()
    namespaces = namespaces.items

    if namespace not in [namespace.metadata.name for namespace in namespaces]:
        print(f"Namespace {args.namespace} does not exist")
        sys.exit(1)

    try:
        graph = api.get_namespaced_custom_object(
            "rampart.petuum.com", "v1beta1", namespace, "rampartgraphs", name)
    except kubernetes.client.exceptions.ApiException as e:
        if e.status == 404 and "Not Found" in str(e.reason):
            print(f"Rampart graph {args.namespace}/{args.name} not found. Aborting.")
            sys.exit(1)
        raise e

    with tempfile.TemporaryDirectory() as directory:
        filename = os.path.join(directory, "graph_specification.yaml")
        with open(filename, "w") as f:
            yaml.dump(graph["spec"]["graph"], f)
            editor = os.environ.get("EDITOR", None)
            if not editor:
                print("Default editor not found. Please set the environment variable EDITOR. "
                      "Aborting.")
                exit(1)
        os.system(f"{editor} {filename}")
        with open(filename, "r") as f:
            try:
                new_graph_specification = yaml.safe_load(f)
            except yaml.parser.ParserError as e:
                print("Unable to parse edited specification. "
                      "See the following error for details:\n")
                print(e)
                exit(1)
        graph["spec"]["graph"] = new_graph_specification

    version = graph["metadata"]["resourceVersion"]
    graph["metadata"]["resourceVersion"] = version
    graph["metadata"]["name"] = name

    try:
        result = api.replace_namespaced_custom_object(
            "rampart.petuum.com", "v1beta1", namespace, "rampartgraphs", name, graph)
        print("Rampart graph modified: ")
        print(f"\tNamespace: {result['metadata']['namespace']}")
        print(f"\tName: {result['metadata']['name']}")
        print(f"\tUID: {result['metadata']['uid']}")

    except kubernetes.client.exceptions.ApiException as e:
        if e.reason == "Unprocessable Entity":
            body = yaml.safe_load(e.body)
            print("Edit failed: invalid graph. See the following message:\n")
            print(body["message"])
            exit(1)


def register_edit_graph(subparsers):
    parser_edit = subparsers.add_parser(
        "edit", help="edit a deployed rampart graph with your default command line editor")
    parser_edit.add_argument(
        "name", type=str,
        help=("Graph to edit"))
    parser_edit.add_argument(
        "-n", "--namespace", type=str, default="default",
        help=("Optional. Defaults to \"default\"."))
    parser_edit.set_defaults(handler=handle_edit_graph)
