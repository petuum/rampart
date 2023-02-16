# Copyright 2023 Petuum, Inc. All Rights Reserved.

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
