# Copyright 2023 Petuum, Inc. All Rights Reserved.

import os
import pulsar
import yaml


component_name = os.environ["COMPONENT_NAME"]

pulsar_inputs = {}

pulsar_client_addr = None
client = None


pulsar_input_edges = {}
for env_var, value in os.environ.items():
    if env_var.startswith("RAMPART_INPUT_") and value.startswith("pulsar://"):
        edge_name = env_var[len("RAMPART_INPUT_"):]
        pulsar_input_edges[edge_name] = "/".join(value.split("/")[-3:])
        if not pulsar_client_addr:
            pulsar_client_addr = "/".join(value.split("/")[:-3])

if pulsar_client_addr:
    client = pulsar.Client(pulsar_client_addr, log_conf_file_path="/dev/null")

consumers = {}
for edge_name, topic in pulsar_input_edges.items():
    consumers[edge_name] = client.subscribe(topic, f"{component_name}-{topic}")
    pulsar_inputs[edge_name] = set()


def consume(edge):
    consumer = consumers[edge]
    try:
        msg = consumer.receive(timeout_millis=100)
    except Exception:
        return
    pulsar_inputs[edge].add(msg.data().decode("utf-8"))
    consumer.acknowledge(msg)


while len(pulsar_input_edges):
    for edge in pulsar_input_edges.keys():
        consume(edge)
    with open("/inputs_temp.yaml", "w") as f:
        result = {key: inputs for key, inputs in pulsar_inputs.items()}
        f.write(yaml.dump(result))
    os.replace("/inputs_temp.yaml", "/inputs.yaml")
