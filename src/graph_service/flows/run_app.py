# Copyright 2023 Petuum, Inc. All Rights Reserved.

"""
Provides endpoints for an individual flow that the graph_service.run_app module can
query. Generally these endpoints involve retreiving the actual data from volume
and repo flows, which involves mounting PVC's for the flows. For this reason it is
not feasible to have this functionality performed by the main graph_service module,
as that is only deployed once on the cluster.
"""

import asyncio
import os
import tempfile

from asyncio.subprocess import create_subprocess_exec, PIPE

from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import JSONResponse, FileResponse
import logging
app = FastAPI()

directory_endpoint = "/api/v1/app/flows_service/{flow_title}/directory"
file_endpoint = "/api/v1/app/flows_service/{flow_title}/file"
git_metadata_endpoint = "/api/v1/app/flows_service/{flow_title}/repo-metadata"
git_directory_endpoint = "/api/v1/app/flows_service/{flow_title}/repo-directory"
git_file_endpoint = "/api/v1/app/flows_service/{flow_title}/repo-file"
git_health_check = "/api/v1/app/flows_service/{flow_title}/repo-check"

root_dir = "/volume_flow_mount"
TIMEOUT = 20

LOGGING_FORMAT = '%(asctime)s:  %(message)s'
logging.basicConfig(format=LOGGING_FORMAT)
LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)


async def run_git_command(repo_dir, args):
    if not os.path.exists(repo_dir):
        raise HTTPException(status_code=500, detail="Invalid git repository path:" + repo_dir)

    proc = await create_subprocess_exec(*args, stdout=PIPE, stderr=PIPE, cwd=repo_dir)
    stdout, stderr = await asyncio.wait_for(proc.communicate(), TIMEOUT)
    if proc.returncode:
        raise HTTPException(status_code=500,
                            detail=f'Git error: '
                                   f'error code {proc.returncode} with message {stderr.decode()}')
    return stdout


async def create_temp_file(flow_title, path, branch=None, tag=None):
    norm_real_path, rel_path = validate_path(flow_title, path)
    flow_path = os.path.join(root_dir, flow_title)

    if tag:
        branch = tag
    args = ["git", "show", f"{branch}:{rel_path}"]

    resp = await run_git_command(flow_path, args)

    tmp, path = tempfile.mkstemp()
    with os.fdopen(tmp, 'wb') as f:
        f.write(resp)
    try:
        yield path
    finally:
        os.unlink(path)


def validate_path(flow_title, path):
    flow_path = os.path.join(root_dir, flow_title)
    real_path = os.path.join(flow_path, path.lstrip("/"))

    norm_real_path = os.path.normpath(real_path)
    rel_path = os.path.relpath(norm_real_path, flow_path)
    if rel_path.startswith(".."):
        raise HTTPException(status_code=400, detail="Illegal request path: " + path)

    return norm_real_path, rel_path


@app.get(directory_endpoint)
async def get_volume_tree(flow_title, path):
    norm_real_path, rel_path = validate_path(flow_title, path)
    contents = []
    for f in os.listdir(norm_real_path):
        if os.path.isfile(os.path.join(norm_real_path, f)):
            contents.append({"path": [] if rel_path == '.' else rel_path.split("/"),
                             "name": f,
                             "type": "file"})
        else:
            contents.append({"path": [] if rel_path == '.' else rel_path.split("/"),
                             "name": f,
                             "type": "directory"})
    return JSONResponse(
        status_code=200,
        content={"path": [] if rel_path == '.' else rel_path.split("/"),
                 "contents": contents})


@app.get(file_endpoint, response_class=FileResponse)
async def get_volume_file(flow_title, path):
    norm_real_path, _ = validate_path(flow_title, path)
    if os.path.exists(norm_real_path):
        return norm_real_path
    raise HTTPException(status_code=404, detail="File not found")


@app.get(git_directory_endpoint)
async def get_git_tree(flow_title, path, branch=None, tag=None):
    repo_dir = os.path.join(root_dir, flow_title)
    is_bare_clone = await check_bare_clone(repo_dir)
    if is_bare_clone:
        flow_title += "/bare_clone"
    norm_real_path, rel_path = validate_path(flow_title, path)

    if tag:
        branch = tag
    args = ["git", "ls-tree", branch, "."]

    resp = await run_git_command(norm_real_path, args)
    result = resp.decode('UTF-8').split("\n")[:-1]

    file_list = [{
        "path": [] if rel_path == '.' else rel_path.split("/"),
        "name": each.split("\t")[-1],
        "type": "directory" if each.split(" ")[1] == "tree" else "file"}
        for each in result]

    return {"branch": branch,
            "path": [] if rel_path == '.' else rel_path.split("/"),
            "contents": file_list}


@app.get(git_file_endpoint, response_class=FileResponse)
async def get_git_file(file_path=Depends(create_temp_file)):
    return FileResponse(file_path)


async def check_bare_clone(repo_dir):
    args = ["git", "status"]
    try:
        await run_git_command(repo_dir, args)
    except Exception:
        if os.path.exists(os.path.join(repo_dir, "bare_clone")):
            return True

    return False


@app.get(git_metadata_endpoint)
async def get_git_metadata(flow_title):
    """Returns all the relevant branch and tag information about a flow"""
    repo_dir = os.path.join(root_dir, flow_title)
    is_bare_clone = await check_bare_clone(repo_dir)
    if is_bare_clone:
        repo_dir = os.path.join(repo_dir, "bare_clone")
    args = ["git", "rev-parse", "--abbrev-ref", "HEAD"]
    resp = await run_git_command(repo_dir, args)
    default_branch = resp.decode('UTF-8').split("\n")[0]
    args = ["git", "branch", "-l"]
    resp = await run_git_command(repo_dir, args)
    branches = resp.decode('UTF-8').strip().split("\n")
    args = ["git", "tag", "-l"]
    resp = await run_git_command(repo_dir, args)
    tags = resp.decode('UTF-8').strip().split("\n")
    return {
            "defaultBranch": default_branch,
            "branches": branches,
            "tags": tags}


@app.get(git_health_check)
async def git_health_check(flow_title):
    """Check if the git flow is working"""
    repo_dir = os.path.join(root_dir, flow_title)
    is_bare_clone = await check_bare_clone(repo_dir)
    if is_bare_clone:
        repo_dir = os.path.join(repo_dir, "bare_clone")

    # Touch the /tmp on the fly
    try:
        tempfile.TemporaryFile(dir=repo_dir)
    except FileNotFoundError:
        return {"status": "error"}

    # Rung Git status
    args = ["git", "status"]
    try:
        await run_git_command(repo_dir, args)
    except HTTPException:
        return {"status": "error"}
    else:
        return {"status": "normal"}
