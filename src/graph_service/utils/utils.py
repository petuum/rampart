# Copyright 2023 Petuum, Inc. All Rights Reserved.

import copy
import hashlib
import json
import uuid
import httpx

from operator import itemgetter
from tinydb import TinyDB, Query

graph_versions_db = TinyDB('/etc/graphs/versions.json')


def filter_metadata(graph_obj):
    """Remove all kubernetes metadata besides name and namespace, and remove the `deploy` field"""
    if "metadata" not in graph_obj:
        return

    graph_obj = copy.deepcopy(graph_obj)
    graph_obj["metadata"] = {key: value for key, value in graph_obj["metadata"].items()
                             if key == "name" or key == "namespace"}
    if "deploy" in graph_obj["spec"]:
        del graph_obj["spec"]["deploy"]
    return graph_obj


# From https://www.doc.ic.ac.uk/~nuric
def dict_hash(dictionary):
    """MD5 hash of a dictionary."""
    dhash = hashlib.md5()
    # We need to sort arguments so {'a': 1, 'b': 2} is
    # the same as {'b': 2, 'a': 1}
    encoded = json.dumps(dictionary, sort_keys=True).encode()
    dhash.update(encoded)
    return dhash.hexdigest()


def app_id_from_metadata(metadata):
    return f"{metadata['namespace']}_{metadata['name']}"


def get_latest_version(namespace, name):
    """Returns the highest version number for an app"""
    graph_query = Query()
    graph_versions = graph_versions_db.search((graph_query.namespace == namespace)
                                              & (graph_query.name == name))
    if len(graph_versions) > 0:
        sorted_graph_versions = sorted(graph_versions, key=itemgetter('version'))
        return sorted_graph_versions[-1]['version']
    else:
        return 0


def is_readonly_app(metadata):
    if metadata.get("labels") is not None \
            and metadata["labels"].get("rampart-graph-readonly", "false") == "true":
        return True
    return False


def generate_uuid_str():
    return uuid.uuid4().hex


async def request(url, params):
    async with httpx.AsyncClient() as client:
        if params:
            result = await client.get(url, params=params)
        else:
            result = await client.get(url)
        return result
