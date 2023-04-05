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

import os
import pulsar
import time

from pathlib import Path


component_name = os.environ["COMPONENT_NAME"]


pulsar_output_edges = {}
pulsar_client_addr = None
client = None
for env_var, value in os.environ.items():
    if env_var.startswith("RAMPART_OUTPUT_") and value.startswith("pulsar://"):
        edge_name = env_var[len("RAMPART_OUTPUT_"):]
        pulsar_output_edges[edge_name] = "/".join(value.split("/")[-3:])
        if not pulsar_client_addr:
            pulsar_client_addr = "/".join(value.split("/")[:-3])

if pulsar_client_addr:
    client = pulsar.Client(pulsar_client_addr)
producers = {}
time.sleep(1)

for topic in pulsar_output_edges.values():
    producers[topic] = client.create_producer(topic)


def produce(edge, topic):
    producer = producers[topic]
    producer.send(str.encode(str([component_name, edge])))


while True:
    for edge, topic in pulsar_output_edges.items():
        produce(edge, topic)
    Path("/.sent").touch()
    time.sleep(1)
