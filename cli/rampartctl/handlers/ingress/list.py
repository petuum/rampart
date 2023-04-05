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
import subprocess


def handle_get_ingress(args, remaining, help_fn):
    # TODO: Make this robust
    # TODO: Add ingress to some existing compoents (like tensorboard) and test with this
    api = kubernetes.client.ExtensionsV1beta1Api()

    graph_name = dict(args._get_kwargs())["graph-name"]
    component_name = dict(args._get_kwargs())["component-name"]

    # TODO: Use the component namespaces from the graph rather than hardcoded?
    namespace = f"{graph_name}-{component_name}"

    ingress_objs = api.list_namespaced_ingress(namespace)
    # TODO: newer ingress versions
    if not ingress_objs.items:
        print(f"No ingress resources found in {namespace}")
    for obj in ingress_objs.items:
        if obj.status.load_balancer.ingress[0].hostname:
            host = obj.status.load_balancer.ingress[0].hostname
        else:
            host = obj.status.load_balancer.ingress[0].ip
        for rule in obj.spec.rules:
            if rule.host and "*" not in rule.host:
                rule_host = rule.host
            else:
                rule_host = host
            for path in rule.http.paths:
                url = f'http://{rule_host}{path.path}'
                if args.open:
                    subprocess.run(["open", url])
                else:
                    print(url)


def register_list_ingress(subparsers):
    parser_link = subparsers.add_parser(
        "link", help="get all ingress endpoints for a component of a graph")
    parser_link.add_argument("graph-name", type=str, help="name of the graph")
    parser_link.add_argument("component-name", type=str, help="name of the component")
    parser_link.add_argument("--open", action="store_true", help="open the url's")
    parser_link.set_defaults(handler=handle_get_ingress)
