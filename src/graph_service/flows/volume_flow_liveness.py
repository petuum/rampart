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
    """Parses .RAMPART/edges.yaml in a volume flow to return the edges for this component"""
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
    """Parses .RAMPART/edges.yaml in a volume flow to return the current component"""
    with open("/.RAMPART/component.yaml", "r") as f:
        return f.readline().strip()


app = FastAPI()

component = get_component()


def write(path, edge_name):
    """
    Writes to a file in .RAMPART for this component and the provided edge_name.
    If this file is written to, then other services knows that this component can write
    to the flow.
    """
    os.makedirs(f"{path}/.RAMPART", exist_ok=True)
    os.makedirs(f"{path}/.RAMPART/{component}", exist_ok=True)
    with open(f"{path}/.RAMPART/{component}/{edge_name}.in", "w") as f:
        f.write("foo")
    return f"{path}/.RAMPART/{component}/{edge_name}.in"


async def read(path):
    """
    Reads all files that this component has access to for the volume flow defined
    by `path`
    """
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
    """
    Writes to a file on the flow for a given edge,
    and returns a handler that we can later call to check that we did write
    """
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


# Write to all outputs and store their handlers from `create_output_liveness```
output_handlers = {}

outputs, inputs = get_edges()
for edge_name in outputs:
    path = os.environ[f"RAMPART_OUTPUT_{edge_name}"]
    output_handlers[edge_name] = create_output_liveness(path, edge_name)


@app.get(OUTPUT_LIVENESS_PATH)
async def handle_output(edge):
    """
    Use the handler created on start to check that we can write to a given output edge
    """
    if edge not in outputs:
        return HTTPException(status_code=404, detail="Edge not found")
    handler = output_handlers[edge]
    return await handler()


@app.get(INPUT_LIVENESS_PATH)
async def handle_input(edge):
    """
    Read from all the available edges on the flow to return which ones we can read from
    """
    print(f"edge: {edge}")
    print(f"inputs: {inputs}")
    if edge not in inputs:
        return HTTPException(status_code=404, detail="Edge not found")
    path = os.environ[f"RAMPART_INPUT_{edge}"]
    edges = await read(path)
    return list(edges)
