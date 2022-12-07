# Copyright 2023 Petuum, Inc. All Rights Reserved.
import pytest
import tests.helpers.component_pool as comp_pool
from src.graph.utils.classes import ValidationError


@pytest.mark.asyncio
@pytest.mark.parametrize("components,annotations", [(comp_pool.annotation_overlap_io,
                                                     comp_pool.annotations_overlap_io),
                                                    (comp_pool.annotation_normal,
                                                     comp_pool.annotations_normal)],
                         ids=["overlap_io", "normal"])
async def test_initialize_no_error(components, annotations, run_chart_initialize):
    comp_charts = run_chart_initialize(components)
    for annotation, chart in zip(annotations, comp_charts):
        await chart.validate()
        comp_spec = chart._component_spec
        assert comp_spec.input_specs.keys() == {edge["name"] for edge in annotation["inputs"]}
        assert comp_spec.output_specs.keys() == {edge["name"] for edge in annotation["outputs"]}


@pytest.mark.asyncio
@pytest.mark.parametrize("components", [comp_pool.annotation_schema_invalid,
                                        comp_pool.annotation_duplicate_io,
                                        comp_pool.annotation_conflict_io,
                                        comp_pool.annotation_invalid_mount_path],
                         ids=["invalid_schema", "duplicate_io",
                              "conflict_io", "invalid_mount_path"])
async def test_validate_error(components, run_chart_initialize):
    comp_chart = run_chart_initialize(components)
    for chart in comp_chart:
        with pytest.raises(ValidationError) as e:
            await chart.validate()
        assert len(e.value.errors) == 1
