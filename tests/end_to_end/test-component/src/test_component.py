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

from volume_flow_liveness import handle_input
from volume_flow_liveness import inputs as volume_inputs

from aiohttp import web
from fastapi import FastAPI
from git import Repo

import asyncio
import os
import subprocess
import yaml


component_name = os.environ["COMPONENT_NAME"]

git_output_mounts = {}
git_input_mounts = {}
for env_var, value in os.environ.items():
    if env_var.startswith("RAMPART_OUTPUT_") and "repository" in env_var:
        name = env_var[len("RAMPART_OUTPUT_"):]
        git_output_mounts[name] = value
    elif env_var.startswith("RAMPART_INPUT_") and "repository" in env_var:
        name = env_var[len("RAMPART_INPUT_"):]
        git_input_mounts[name] = value


for name, mount in git_output_mounts.items():
    subprocess.Popen(
        ["bash", "-c",
         (f"cd {mount} && git checkout -b {component_name}-{name} "
          f"&& git push --set-upstream origin {component_name}-{name}")])
    print(f"creating {component_name}-{name} in {mount}")

app = FastAPI()


@app.get("/healthz")
async def ready():
    if os.path.exists("/.sent"):
        return web.Response(status=200, text='ready')
    else:
        return web.Response(status=404, text='not ready')


async def handle_inputs():
    return await asyncio.gather(*[handle_input(volume_input) for volume_input in volume_inputs])


async def handle_git_repo():
    result = {}
    for name, mount in git_input_mounts.items():
        print(mount)
        repo = Repo(mount)
        branches = []
        repo.git.fetch()
        for line in repo.git.branch('-r').split('\n'):
            print(line)
            line = line.strip()
            if "->" not in line:
                branch = line.split("/")[-1]
                if branch != "main":
                    branches.append(branch)
        print(branches)
        result[name] = [
            [branch[:branch.find("-")], branch[branch.find("-") + 1:]] for branch in branches]
    return result


@app.get("/inputs")
async def list_inputs():
    volume_connections = await asyncio.gather(
        *[handle_input(volume_input) for volume_input in volume_inputs])
    volume_connections = dict(zip(volume_inputs, volume_connections))
    if os.path.exists("/inputs.yaml"):
        with open("/inputs.yaml", "r") as f:
            pulsar_inputs = yaml.safe_load(f)
    else:
        pulsar_inputs = {}
    repo_connections = await handle_git_repo()
    pulsar_connections = {
        edge_name: list(components) for edge_name, components in pulsar_inputs.items()}
    return component_name, volume_connections, pulsar_connections, repo_connections
