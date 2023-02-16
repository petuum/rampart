# Copyright 2023 Petuum, Inc. All Rights Reserved.
from copy import copy

import pytest

from src.graph.objects.base_types import BaseElement, KubernetesName, Metadata


@pytest.fixture(scope="module")
def graph_metadata():
    return Metadata("testnamespace", "testname", "testuid")


@pytest.mark.asyncio
async def test_test_element():
    class TestElement(BaseElement):
        async def deploy(self):
            return await super().deploy()

        async def validate(self):
            return await super().validate()

    metadata = Metadata("namespace", "name", "uid")
    test_element = TestElement(metadata)
    assert not test_element.validated
    assert test_element.namespace == "namespace"
    assert test_element.name == "name"
    assert test_element.uid == "uid"
    assert test_element.metadata == metadata

    try:
        BaseElement(metadata)
    except TypeError as e:
        assert "abstract" in str(e)
    else:
        raise RuntimeError("Expected failure: class should be abstract")


@pytest.mark.asyncio
async def test_kubernetes_name():
    name_1 = "Kuberentes-Name-sample_value-123412"
    kubernetes_view = "Kuberentes-Name-sample-value-123412"
    rampart_view = "Kuberentes_Name_sample_value_123412"

    name_2 = "Kuberentes-Name-sample_valuf-123412"
    kubernetes_name = KubernetesName(name_1)

    assert kubernetes_name
    assert (not KubernetesName(""))

    assert str(kubernetes_name) == rampart_view

    assert kubernetes_name < KubernetesName(name_2)
    assert KubernetesName(name_2) > kubernetes_name
    assert kubernetes_name == kubernetes_name
    assert kubernetes_name == KubernetesName(name_1)
    assert kubernetes_name == rampart_view

    assert hash(kubernetes_name) == hash(KubernetesName(name_1))
    assert hash(kubernetes_name) != hash(KubernetesName(name_2))

    assert repr(kubernetes_name)

    assert kubernetes_name.original_view == name_1
    assert kubernetes_name.kubernetes_view == kubernetes_view
    assert kubernetes_name.rampart_view == rampart_view


@pytest.mark.asyncio
async def test_metadata():
    metadata_1 = Metadata("namespace", "name", "uid")
    metadata_2 = Metadata("namespace2", "name-2", "uid2")
    metadata_3 = Metadata(metadata_1, "name", "uid")
    metadata_4 = Metadata(None, "name_4", "uid")

    assert str(metadata_1) != str(metadata_4)
    assert str(metadata_3) == str(metadata_3)

    assert repr(metadata_2) != repr(metadata_3)
    assert repr(metadata_4) == repr(metadata_4)

    assert not (metadata_1 == 3)

    assert metadata_3 == Metadata(metadata_1, "name", "uid")
    assert not (metadata_3 == metadata_1)

    assert hash(metadata_3) == hash(Metadata(metadata_1, "name", "uid"))
    assert hash(metadata_3) != hash(metadata_1)
    assert hash(metadata_3) != hash(metadata_2)
    assert hash(metadata_3) != hash(metadata_4)

    assert metadata_3 == copy(metadata_3)
    assert id(metadata_3) != id(copy(metadata_3))
    assert id(copy(metadata_3)) != id(copy(metadata_3))

    assert metadata_2 == copy(metadata_2)
    assert metadata_2 != copy(metadata_3)
    assert id(metadata_2) != id(copy(metadata_2))
    assert id(copy(metadata_2)) != id(copy(metadata_2))

    assert metadata_1.namespace == KubernetesName("namespace")
    assert metadata_2.namespace == KubernetesName("namespace2")
    assert metadata_3.namespace == metadata_1
    assert metadata_4.namespace == KubernetesName("None")

    assert metadata_1.name == KubernetesName("name")
    assert metadata_2.name == KubernetesName("name-2")
    assert metadata_3.name == KubernetesName("name")
    assert metadata_4.name == KubernetesName("name_4")

    assert metadata_1.uid == "uid"
    assert metadata_2.uid == "uid2"
    assert metadata_3.uid == "uid"
    assert metadata_4.uid == "uid"

    assert metadata_1.kubernetes_view == "name"
    assert metadata_2.kubernetes_view == "name-2"
    assert metadata_3.kubernetes_view == "name"
    assert metadata_4.kubernetes_view == "name-4"

    assert metadata_1.rampart_view == "name"
    assert metadata_2.rampart_view == "name_2"
    assert metadata_3.rampart_view == "name"
    assert metadata_4.rampart_view == "name_4"

    metadata_4.uid = "hello"
    assert metadata_4.uid == "hello"
