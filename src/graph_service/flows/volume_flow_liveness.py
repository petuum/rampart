# Copyright 2023 Petuum, Inc. All Rights Reserved.

import glob
import os
import yaml

from fastapi import FastAPI, HTTPException

outputs = {}
inputs = {}

OUTPUT_LIVENESS_PATH = "/output/{edge}"
INPUT_LIVENESS_PATH = "/input/{edge}"


def get_edges():
    with open("/.RAMPART/edges.yaml", "r") as f:
        edges_yaml = yaml.safe_load(f)
    outputs = set()
    inputs = set()
    for body in edges_yaml:
        name = body["name"]
        if "VOLUME" in body["type"]:
            if "OUTPUT" in body["part"]:
                outputs.add(name)
            elif "INPUT" in body["part"]:
                inputs.add(name)
    return outputs, inputs


def get_component():
    with open("/.RAMPART/component.yaml", "r") as f:
        return f.readline().strip()


app = FastAPI()

component = get_component()


def write(path, edge_name):
    os.makedirs(f"{path}/.RAMPART", exist_ok=True)
    os.makedirs(f"{path}/.RAMPART/{component}", exist_ok=True)
    with open(f"{path}/.RAMPART/{component}/{edge_name}.in", "w") as f:
        f.write("foo")
    return f"{path}/.RAMPART/{component}/{edge_name}.in"


async def read(path):
    path = f"{path}/.RAMPART/"
    paths = glob.glob(f"{path}**/*.in", recursive=True)
    found = set()
    for path in paths:
        try:
            with open(path, "r") as f:
                if (["foo"] == f.readlines()):
                    elements = path.split("/")
                    edge_name = elements[-1][:-len(".in")]
                    component = elements[-2]
                    found.add((component, edge_name))
        except IOError:
            pass
    return found


def create_output_liveness(path, edge_name):
    path = write(path, edge_name)

    async def handler():
        if not os.path.exists(path):
            return False
        try:
            with open(path, "r") as f:
                return (["foo"] == f.readlines())
        except IOError:
            return False
    return handler


output_handlers = {}

outputs, inputs = get_edges()

for edge_name in outputs:
    path = os.environ[f"RAMPART_OUTPUT_{edge_name}"]
    output_handlers[edge_name] = create_output_liveness(path, edge_name)


@app.get(OUTPUT_LIVENESS_PATH)
async def handle_output(edge):
    if edge not in outputs:
        return HTTPException(status_code=404, detail="Edge not found")
    handler = output_handlers[edge]
    return await handler()


@app.get(INPUT_LIVENESS_PATH)
async def handle_input(edge):
    print(f"edge: {edge}")
    print(f"inputs: {inputs}")
    if edge not in inputs:
        return HTTPException(status_code=404, detail="Edge not found")
    path = os.environ[f"RAMPART_INPUT_{edge}"]
    edges = await read(path)
    return list(edges)
