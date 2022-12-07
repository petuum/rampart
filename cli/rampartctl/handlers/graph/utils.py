# Copyright 2023 Petuum, Inc. All Rights Reserved.
import urllib

from collections.abc import Mapping

import yaml
try:
    from yaml import CSafeLoader as Loader, CSafeDumper as Dumper
except ImportError:
    from yaml import SafeLoader as Loader, SafeDumper as Dumper # noqa: 401

from ..utils import get_all_custom_objects, ListError


def _merge_dicts(dict1, dict2):
    """Merge two dicts into the first one.
    This is a mirror of `mergeMaps` function in helm's source code.
    https://github.com/helm/helm/blob/efe2638f87b597403f34009e1029a6f0b44db8f2/pkg/cli/values/options.go#L88""" # noqa
    # for the sake of avoiding recursion
    stack = [(dict1, dict2)]
    while stack:
        d1, d2 = stack.pop()
        for k, v in d2.items():
            if isinstance(v, Mapping):
                if k in d1:
                    if isinstance(d1[k], Mapping):
                        stack.append((d1[k], v))
                        continue
            d1[k] = v


def _is_url(string):
    return any([string.startswith(resource) for resource in ["http://", "https://", "ftp://"]])


def _read_values(values_path):
    if urllib.parse.urlparse(values_path).scheme.lower() in ["http", "https", "ftp"]:
        with urllib.request.urlopen(values_path) as f:
            values = yaml.safe_load(f)
    else:
        with open(values_path, "rb") as f:
            values = yaml.safe_load(f)
    return values


def merge_values(graph, graph_filename, values_list):
    # values_list elements must be in the form <component>=<path> or <path>
    if not values_list:
        return

    for value_text in values_list:
        parsed_value = value_text.split("=")
        if _is_url(value_text) or len(parsed_value) == 1:
            components = graph["spec"]["graph"]["components"].keys()
            value_path = value_text
        else:
            component_name = parsed_value[0]
            value_path = "=".join(parsed_value[1:])
            if component_name not in graph["spec"]["graph"]["components"]:
                if not graph_filename:
                    raise RuntimeError(f"{component_name} is not a component in the graph")
                raise RuntimeError(f"{component_name} is not a component in {graph_filename}")
            components = [component_name]
        for component_name in components:
            component_values = graph["spec"]["graph"]["components"][component_name]["values"]
        _merge_dicts(component_values, _read_values(value_path))


def get_all_graphs(args):
    try:
        objects = get_all_custom_objects(args, "rampartgraphs")
    except ListError as e:
        print(e.message.format("graphs"))
    return objects
