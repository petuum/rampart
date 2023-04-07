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

import kubernetes_asyncio as kubernetes


def generate_namespace(name):
    return kubernetes.client.V1Namespace(
        "v1", "Namespace", kubernetes.client.V1ObjectMeta(name="name"))


def generate_rampart_graphs():
    return [{
        "metadata": {
            "name": "test-graph-2",
            "namespace": "default"},
        "spec": {
            "deploy": True,
            "graph": {
                "flows": {},
                "components": {
                    "c1": {
                        "namespace": "test1"},
                    "c2": {}}}}}, {
        "metadata": {
            "name": "testname",
            "namespace": "testnamespace"},
        "spec": {
            "deploy": True,
            "graph": {
                "flows": {},
                "components": {
                    "component2": {}}}}}]
