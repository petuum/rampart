# Copyright 2023 Petuum, Inc. All Rights Reserved.

import subprocess
import os
import uuid

import yaml
try:
    from yaml import CSafeLoader as Loader, CSafeDumper as Dumper
except ImportError:
    from yaml import SafeLoader as Loader, SafeDumper as Dumper  # noqa: 401


def _get_yaml_output(command):
    command_result = subprocess.run(command, capture_output=True)
    if command_result.returncode != 0:
        raise RuntimeError(command_result.stderr)
    else:
        return yaml.load(command_result.stdout, Loader=Loader)


def _get_or_make_cached_repo_name(url):
    command = ["helm", "repo", "list", "-o", "yaml"]
    repos = _get_yaml_output(command)
    for repo in repos:
        if repo["url"] == url:
            return repo["name"]
    uid = str(uuid.uuid4())[:8]
    name = f"rampart-repo-{uid}"
    command = ["helm", "repo", "add", name, url]
    subprocess.run(command)
    return name


def _get_components(repo_name):
    command = ["helm", "search", "repo", repo_name, "--devel", "-o", "yaml"]
    return _get_yaml_output(command)


def _get_component_descriptions(repo_name):
    cache_command = ["helm", "env"]
    result = subprocess.run(cache_command, capture_output=True).stdout
    directory = None
    for line in result.splitlines():
        line = line.decode("utf-8")
        if line.startswith("HELM_REPOSITORY_CACHE="):
            directory = line.split("=")[1].strip('"')
    if not directory:
        raise RuntimeError("Could not find local helm repository cache")

    path = os.path.join(directory, f"{repo_name}-index.yaml")
    components = yaml.load(open(path, 'r'), Loader=yaml.Loader)
    return components["entries"]


def handle_list_components(args, remaining, help_fn):
    repo_name = _get_or_make_cached_repo_name(args.url)
    if args.describe:
        components = _get_component_descriptions(repo_name)
        component_specs_yaml = []
        for version_list in components.values():
            description = version_list[0]  # Latest is at top according to helm specification
            try:
                component_yaml = {
                    'name': description['name'],
                    'version': description['version']}
                if ("annotations" in description and
                        "petuum/rampartComponent" in description["annotations"]):
                    component_yaml['spec'] = yaml.load(
                        description['annotations']['petuum/rampartComponent'],
                        Loader=Loader)
                component_specs_yaml.append(component_yaml)
            except RuntimeError as e:
                if "failed to download" in str(e.args[0]):
                    pass
        print("\n---\n\n".join([yaml.dump(comp) for comp in component_specs_yaml]))
    else:
        components = _get_components(repo_name)
        component_specs_yaml = []
        for component in components:
            component_specs_yaml += [{
               'name': component['name'],
               'version': component['version'],
            }]

        def format_version(name, version):
            GAP = 63
            return name + " " * (GAP - len(name)) + version

        print(format_version("CHART NAME", "VERSION"))
        for comp_spec in component_specs_yaml:
            name = comp_spec["name"]
            version = comp_spec["version"]
            print(format_version(name, version))


def register_list_components(subparsers):
    parser_list = subparsers.add_parser(
        "list-components", help="list all component specifications on a remote repository")
    parser_list.add_argument("url", type=str, help="URL of the remote repository")
    parser_list.add_argument(
        "-d", "--describe", action='store_true',
        help="Print out a verbose description of the component specifications")
    parser_list.set_defaults(handler=handle_list_components)
