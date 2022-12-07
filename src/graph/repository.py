# Copyright 2023 Petuum, Inc. All Rights Reserved.

import asyncio
import collections
import copy
import logging
import yaml

import kubernetes_asyncio as kubernetes
from .constants import COMPONENT_SPEC_KEY, LOGGING_FORMAT, \
                       REPO_TIMEOUT, RAMPART_INFRA_K8S_KEY_GEN
from .utils.classes import GraphPhase, SubprocessArgs, ValidationError
from .utils.logger import GraphLogger


kubernetes.config.load_incluster_config()

logging.basicConfig(format=LOGGING_FORMAT)
LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)


class _ComponentID:
    def __init__(self, repo_url, chart_name, chart_version):
        self._repo_url = repo_url
        self._chart_name = chart_name
        self._chart_version = chart_version

    def __eq__(self, other):
        return (
            self._repo_url == other._repo_url and
            self._chart_name == other._chart_name and
            self._chart_version == other._chart_version)

    def __hash__(self):
        return hash((self._repo_url, self._chart_name, self._chart_version))


class ComponentRepo:
    def __init__(self, name, url, pull_args):
        self._url = url.strip("/")
        self._name = name
        # Mutexes for operations on each chart versions
        self._chart_locks = {}
        # Mutex for operations on self._chart_locks
        self._lock = asyncio.Lock()
        # Usage of this cache assumes that a versioned chart never changes
        self._annotations_cache = {}
        self._pull_args: SubprocessArgs = pull_args
        self._key = self.generate_key(self._name, self._pull_args)

    @property
    def secret(self):
        return self._secret

    @property
    def url(self):
        return self._url

    @property
    def name(self):
        return self._name

    @property
    def key(self):
        return self._key

    @staticmethod
    def generate_key(name, pull_args: SubprocessArgs):
        if pull_args:
            pull_args_hash = hash(pull_args)
        else:
            pull_args_hash = hash('%')
        return (name, pull_args_hash)

    async def update_repo(self, metadata=None):
        #  TODO: add caching
        logger = GraphLogger(LOG, {"metadata": metadata})
        logger.info(f"adding repo {self.url}", extra={"phase": GraphPhase.VALIDATION})
        args = ["helm", "repo", "add", self.name, self.url, "--force-update"]
        stdin = None
        if self._pull_args:
            args += self._pull_args.exec_args
            stdin = self._pull_args.stdin_input.encode()
        proc = await asyncio.subprocess.create_subprocess_exec(*args,
                                                               stdin=asyncio.subprocess.PIPE,
                                                               stdout=asyncio.subprocess.PIPE,
                                                               stderr=asyncio.subprocess.PIPE)
        try:
            _, stderr = await asyncio.wait_for(proc.communicate(stdin), timeout=REPO_TIMEOUT)
        except asyncio.TimeoutError:
            logger.warning(f"timeout error for adding repo {self.url}",
                           extra={"phase": GraphPhase.VALIDATION})
            raise ValidationError({f"Failed to add repo {self.name} whose url is {self.url}.\n"
                                   "Operation timed out"})

        if proc.returncode:
            raise ValidationError({f"Failed to add repo {self.name} whose url is {self.url}.\n"
                                   f"{stderr.decode()}"})

    async def get_component_annotations(self, comp_name, comp_version, metadata=None):
        logger = GraphLogger(LOG, {"metadata": metadata})
        key = (comp_name, comp_version)
        async with self._lock:
            if key not in self._chart_locks:
                self._chart_locks[key] = asyncio.Lock()
        async with self._chart_locks[key]:
            if key in self._annotations_cache:
                return self._annotations_cache[key]

            args = ["helm", "show", "chart", f"{self.name}/{comp_name}"]
            stdin = None
            if self._pull_args:
                args += self._pull_args.exec_args
                stdin = self._pull_args.stdin_input.encode()
            if comp_version != "latest":
                args += ["--version", comp_version]
            else:
                # TODO: block unstable versions
                args += ["--devel"]
            logger.info(f"fetching chart {self.name}/{comp_name}",
                        extra={"phase": GraphPhase.VALIDATION})
            proc = await asyncio.subprocess.create_subprocess_exec(*args,
                                                                   stdin=asyncio.subprocess.PIPE,
                                                                   stdout=asyncio.subprocess.PIPE,
                                                                   stderr=asyncio.subprocess.PIPE)
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(stdin),
                                                        timeout=REPO_TIMEOUT)
            except asyncio.TimeoutError:
                logger.warning(f"timeout error for fetching chart {self.name}/{comp_name}",
                               extra={"phase": GraphPhase.VALIDATION})
                raise ValidationError({f"Failed to show chart for repo {self._url}.\n"
                                       "Operation timed out"})
            if proc.returncode:
                raise ValidationError({f"Failed to get chart descriptions for"
                                       f" {self.name}/{comp_name}\n{stderr.decode()}"})
            try:
                result_yaml = yaml.safe_load(stdout.decode())
            except yaml.YAMLError as error:
                raise ValidationError({f"Error parsing chart descriptions for"
                                       f" {self.name}/{comp_name}, please make sure that"
                                       f" your chart is valid\n{error}"})
            annotations = result_yaml.get("annotations", {}).get(COMPONENT_SPEC_KEY, "")

            # Don't cache latest, in case a new chart is pushed
            if comp_version != "latest":
                self._annotations_cache[key] = annotations
        return annotations


class RepoManager:
    _instance = None

    def __new__(cls):
        """Make RepoManager singleton."""
        if cls._instance is None:
            cls._instance = super(RepoManager, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        self._repos = {}
        self._component_annotations = {}
        self._graph_component_annotations_map = collections.defaultdict(set)
        self._component_annotations_reference_count = collections.defaultdict(set)

        # For keeping track of references to do reference counting GC
        # Note: the counter is a set of references instead of a number
        # for idempotence
        self._graph_repo_map = collections.defaultdict(set)
        self._repo_reference_count = collections.defaultdict(set)

        # Mutexes for operations on individual repos e.g., helm add repo_a repo_url
        self._repo_locks = {}

        self._component_locks = {}

        # Mutex for operations on self._repo_locks
        self._lock = asyncio.Lock()

        self._provided = {}

        self._custom_api = kubernetes.client.CustomObjectsApi()
        self._namespace_api = kubernetes.client.CoreV1Api()

    @property
    def provided(self):
        return copy.deepcopy(self._provided)

    async def update_provides(self):
        namespaces_result = await self._namespace_api.list_namespace()
        namespaces = namespaces_result.items
        tasks = [self._custom_api.list_namespaced_custom_object(
                     *RAMPART_INFRA_K8S_KEY_GEN(namespace.metadata.name))
                 for namespace in namespaces]
        tasks = await asyncio.gather(*tasks)
        provided = {}
        for graphs_response in tasks:
            graphs = graphs_response["items"]
            for graph in graphs:
                if "provides" in graph.get("status", {}):
                    for infra in graph["status"]["provides"]:
                        if infra["status"] in ["registered", "deployed"]:
                            provided[infra["name"]] = infra["source"]

        self._provided = provided

    async def add_or_get_repo(self, repo_name, url, pull_args, graph_metadata):
        repo_key = ComponentRepo.generate_key(repo_name, pull_args)
        async with self._lock:
            if repo_key not in self._repos:
                self._repos[repo_key] = ComponentRepo(repo_name, url, pull_args)
                self._repo_locks[repo_key] = asyncio.Lock()

            self._repo_reference_count[repo_key].add(graph_metadata.uid)
            self._graph_repo_map[graph_metadata.uid].add((repo_name, repo_key))

        return self.get_repo(repo_key)

    def get_repo(self, repo_key):
        return self._repos[repo_key]

    async def gc_graph(self, graph_metadata):
        async with self._lock:
            repos = self._graph_repo_map[graph_metadata.uid]
            for repo_name, repo_key in repos:
                async with self._repo_locks[repo_key]:
                    try:
                        self._repo_reference_count[repo_key].remove(graph_metadata.uid)
                    except KeyError:
                        pass
                    if not len(self._repo_reference_count[repo_key]):
                        args = ["helm", "repo", "remove", repo_name]
                        proc = await asyncio.subprocess.create_subprocess_exec(*args)
                        _, stderr = await proc.communicate()

                        del self._repo_reference_count[repo_key]
                        del self._repos[repo_key]

            for component_id in self._graph_component_annotations_map[graph_metadata]:
                async with self._component_locks[component_id]:
                    try:
                        self._component_annotations_reference_count[component_id]\
                            .remove(graph_metadata)
                    except KeyError:
                        pass
                    if not len(self._component_annotations_reference_count[component_id]):
                        del self._component_annotations_reference_count[component_id]
                        del self._component_annotations[component_id]

            del self._graph_repo_map[graph_metadata.uid]
            del self._graph_component_annotations_map[graph_metadata]


_GLOBAL_REPO_MANAGER = RepoManager()


def get_global_repo_manager():
    return _GLOBAL_REPO_MANAGER
