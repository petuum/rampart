# Copyright 2023 Petuum, Inc. All Rights Reserved.
import pytest
import tempfile
import unittest

import tests.helpers.component_pool as comp_pool

from src.graph.objects.component import _match_variadic_spec_by_name, ComponentInstance
from src.graph.utils.classes import ValidationError
from tests.src.graph.objects.conftest import METADATA

from src.graph.objects.base_types import Metadata


@pytest.mark.asyncio
@pytest.mark.parametrize("components", [comp_pool.type_mismatch_with_spec,
                                        comp_pool.type_mismatch_with_flow,
                                        comp_pool.bad_flow_reference,
                                        comp_pool.overlap_mount_path],
                         ids=["type_mismatch_with_spec", "type_mismatch_with_flow",
                              "bad_flow_reference", "overlap_mount_path"])
async def test_validate_error(components, run_chart_initialize, run_inst_initialize):
    comp_charts = run_chart_initialize(components, True)
    for chart in comp_charts:
        await chart.validate()
    comp_instances = run_inst_initialize(components, comp_charts)
    metadata = Metadata(*METADATA)
    for comp_inst in comp_instances:
        assert comp_inst.namespace is None
        assert comp_inst.name == metadata.name
        assert comp_inst.uid == metadata.uid
        with pytest.raises(ValidationError) as e:
            await comp_inst.validate(True)
        assert len(e.value.errors) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("components", [comp_pool.normal])
async def test_validate_no_error(components, run_chart_initialize, run_inst_initialize):
    comp_charts = run_chart_initialize(components, True)
    comp_instances = run_inst_initialize(components, comp_charts)
    metadata = Metadata(*METADATA)
    for comp_inst in comp_instances:
        assert comp_inst.namespace is None
        assert comp_inst.name == metadata.name
        assert comp_inst.uid == metadata.uid
        await comp_inst.validate(False)
    for chart in comp_charts:
        assert not chart.validated
    for comp_inst in comp_instances:
        await comp_inst.validate(True)
    for chart in comp_charts:
        assert chart.validated


@pytest.mark.asyncio
@pytest.mark.parametrize("components", [comp_pool.normal])
async def test_to_deployment_yaml(components, run_chart_initialize, run_inst_initialize):
    comp_charts = run_chart_initialize(components, True)
    comp_instances = run_inst_initialize(components, comp_charts)
    for comp_inst in comp_instances:
        await comp_inst.validate(True)
        comp_inst._namespace = Metadata(*METADATA)
    for chart in comp_charts:
        assert chart.validated

    for comp_inst in comp_instances:
        with tempfile.TemporaryDirectory() as workdir:
            comp_inst._check_helm_modified = unittest.mock.AsyncMock(
                return_value=False)
            yamls, tasks = await comp_inst.to_deployment_yaml(workdir)
            for yaml in yamls:
                assert yaml["name"] in ["component", "edges"]

                if yaml["name"] == "component":
                    assert yaml["namespace"] == comp_inst.namespace.kubernetes_view
                    assert not yaml.get("recreatePods", False)
                    assert set(yaml["needs"]) == {"edges"}
                    assert yaml["chart"] == comp_inst._chart.name.original_view
                    assert (
                        yaml["version"] == comp_inst._chart.component_spec.version or
                        (
                            comp_inst._chart.component_spec.version == "latest"
                            and yaml["version"] == ">0.0.0-0"))

                    assert "rampart" in yaml["values"][0]
                    assert "inputs" in yaml["values"][0]["rampart"]
                    assert "outputs" in yaml["values"][0]["rampart"]
                    assert "graphName" in yaml["values"][0]["rampart"]
                    assert "namespace" in yaml["values"][0]["rampart"]
                    assert "registry" in yaml["values"][0]["rampart"]
                    assert "URLPrefix" in yaml["values"][0]["rampart"]

                if yaml["name"] == "edges":
                    assert yaml["namespace"] == comp_inst.namespace.kubernetes_view

    for comp_inst in comp_instances:
        with tempfile.TemporaryDirectory() as workdir:
            comp_inst._check_helm_modified = unittest.mock.AsyncMock(
                return_value=True)
            comp_inst._modified_edge = True
            comp_inst._needs = ["test1", "test2"]
            comp_inst._deployment_kwargs = {"test": "value"}
            yamls, tasks = await comp_inst.to_deployment_yaml(workdir)
            for yaml in yamls:
                assert yaml["name"] in ["component", "edges"]

                if yaml["name"] == "component":
                    assert yaml["namespace"] == comp_inst.namespace.kubernetes_view
                    assert yaml["recreatePods"]
                    assert set(yaml["needs"]) == {"test1", "test2", "edges"}
                    assert yaml["chart"] == comp_inst._chart.name.original_view
                    assert (
                        yaml["version"] == comp_inst._chart.component_spec.version or
                        (
                            comp_inst._chart.component_spec.version == "latest"
                            and yaml["version"] == ">0.0.0-0"))

                    assert "rampart" in yaml["values"][0]
                    assert "inputs" in yaml["values"][0]["rampart"]
                    assert "outputs" in yaml["values"][0]["rampart"]
                    assert "graphName" in yaml["values"][0]["rampart"]
                    assert "namespace" in yaml["values"][0]["rampart"]
                    assert "registry" in yaml["values"][0]["rampart"]
                    assert "URLPrefix" in yaml["values"][0]["rampart"]
                    assert yaml["test"] == "value"

                if yaml["name"] == "edges":
                    assert yaml["namespace"] == comp_inst.namespace.kubernetes_view


@pytest.mark.asyncio
async def test_reserved_names():
    component = ComponentInstance(
        Metadata("namespace", "rampart-flows", "uid"),
        {"inputs": {}, "outputs": {}},
        Metadata(*METADATA),
        None,
        None)
    with pytest.raises(ValidationError) as e:
        await component.validate(False)
    assert len(e.value.errors) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("components", [comp_pool.default_mount_path])
async def test_default_mount_path(components, run_chart_initialize, run_inst_initialize):
    comp_charts = run_chart_initialize(components, True)
    for chart in comp_charts:
        await chart.validate()
    comp_instances = run_inst_initialize(components, comp_charts)
    for comp_inst, comp, chart in zip(comp_instances, components, comp_charts):
        await comp_inst.validate()

        def check_default_mount_path(target, target_specs, target_config):
            for name, conf in target.items():
                if conf.type != "volume":
                    continue
                if name in target_specs:
                    default_path = target_specs[name].type_specific_specs.get("mountPath")
                else:
                    match = _match_variadic_spec_by_name(target_specs, name)
                    default_path = None
                    if match:
                        default_path = match.type_specific_specs.get("mountPath")
                    if default_path:
                        default_path = default_path[:-1] + name[len(match.prefix):]
                config_path = target_config[name].get("config", {}).get("mountPath")
                if not config_path and not default_path:
                    assert conf.mount_path == f"/{name}"
                elif not config_path:
                    assert conf.mount_path == default_path
                else:
                    assert conf.mount_path == config_path

        check_default_mount_path(
            comp_inst.inputs, chart.component_spec.input_specs, comp["inputs"])
        check_default_mount_path(
            comp_inst.outputs, chart.component_spec.output_specs, comp["outputs"])
