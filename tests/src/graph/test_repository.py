# Copyright 2023 Petuum, Inc. All Rights Reserved.

from src.graph.constants import LOGGING_FORMAT
import src.graph.repository as repository
from src.graph.objects.component_chart import ComponentChart
from src.graph.objects.base_types import Metadata
import asyncio
import glob
import logging
import pytest
import random
import re
import string
import urllib.parse
import yaml

url_name_re = re.compile("[0-9a-zA-z-]+")

logging.basicConfig(format=LOGGING_FORMAT)
LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)


def _random_urls(str_len, num):
    path_chars = string.ascii_letters + string.digits + string.punctuation
    host_chars = string.ascii_letters + string.digits + "-_~."
    urls = []
    for _ in range(num):
        # hostnames are case insensitive
        host = "".join([random.choice(host_chars) for _ in range(max(str_len // 2, 1))]).lower()
        path = "".join([random.choice(path_chars) for _ in range(str_len - len(host))])
        # deal with special characters
        path = urllib.parse.quote_plus(path)
        urls.append(f"scheme://{host}/{path}")
    return urls


@pytest.mark.parametrize("urls", [[
    "https://test.repo/artifactory/rampart",
    "https://test.repo:8080/artifactory/rampart",
    "https://user1:pass1@test.repo:8080/artifactory/rampart",
    "https://user2:pass1@test.repo:8080/artifactory/rampart",
    "https://user1:@test.repo:8080/artifactory/rampart",
    "https://user1@test.repo:8080/artifactory/rampart",
    "https://:pass1@test.repo:8080/artifactory/rampart",
    "https://test.repo/artifactory+rampart",
    "https://en.wikipedia.org/wiki/Cloud_Native_Computing_Foundation#Helm",
    "https://www.cncf.io/?s=%22helm+++deployment%22",
    "https://www.google.com/search?q=helm%20deployment"],
    _random_urls(10, 1000), _random_urls(100, 1000), _random_urls(1, 1000)])
def test_url_to_name_uniqueness(urls):
    names = set()
    for url in urls:
        component_chart = ComponentChart(
            "test_name", "test_version", url,
            Metadata("test-namespace", "test-name", "test-uid"))
        names.add(component_chart._generate_repo_name())

    assert (len(names) == len(set(urls))), f"urls: {urls} produced duplicate names in {names}"
    for name in names:
        assert (url_name_re.fullmatch(name)), "invalid name, needs to be alphanumeric and - only"


@pytest.mark.parametrize('equivalent_urls', [
    ["https://repo.com/some/path/", "https://repo.com/some/path"],
    ["https://Repo.com/some/path/", "https://repo.com/some/path/"],
])
def test_url_to_name_equivalence_detection(equivalent_urls):
    names = set()
    for url in equivalent_urls:
        component_chart = ComponentChart(
            "test_name", "test_version", url,
            Metadata("test-namespace", "test-name", "test-uid"))
        names.add(component_chart._generate_repo_name())
    assert len(names) == 1


helm_charts = {}

for filename in glob.glob("tests/test_helm/**/Chart.yaml"):
    with open(filename, "r") as f:
        chart = yaml.safe_load(f)
        helm_charts[(chart["name"], chart["version"])] = chart


@pytest.mark.parametrize("component_names, component_versions", [
    (["test_helm_valid_a"] * 5 + ["test_helm_valid_b"] * 5,
     ["0.0.0", "0.1.0", "0.2.0", "0.3.1", "1.1.0", "0.1.5", "0.1.8", "0.5.0", "6.1.0", "100.1.0"]),
    (["test_helm_invalid_a"] * 5 + ["test_helm_invalid_b"] * 5,
     ["0.1.0", "0.2.0", "0.3.0", "0.4.0", "0.5.0", "0.6.0", "0.7.0", "0.8.0", "0.9.0", "0.10.0"])])
def test_get_component_annotations(registry_url, component_names, component_versions):
    repo = repository.ComponentRepo("test_name", registry_url, None)
    asyncio.get_event_loop().run_until_complete(repo.update_repo(None))
    tasks = []
    for component_name, component_version in zip(component_names, component_versions):
        tasks.append(repo.get_component_annotations(component_name, component_version, None))
    annotations = asyncio.get_event_loop().run_until_complete(
        asyncio.gather(*tasks, return_exceptions=True))
    assert (all([
        annotation == helm_charts[(name, version)]["annotations"][repository.COMPONENT_SPEC_KEY]
        for name, version, annotation in zip(component_names, component_versions, annotations)]))
