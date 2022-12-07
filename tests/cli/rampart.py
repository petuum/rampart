# Copyright 2023 Petuum, Inc. All Rights Reserved.

import pytest

from cli.rampartctl.handlers.graph.utils import _merge_dicts


@pytest.mark.parametrize(("dict1", "dict2", "merged"), (
    ({}, {}, {}),
    ({}, {"k1": "v1"}, {"k1": "v1"}),
    ({"k1": "v1"}, {}, {"k1": "v1"}),
    ({"k1": "v1"}, {"k1": {"k21": "v21"}}, {"k1": {"k21": "v21"}}),
    ({"k1": "v1", "k3": {"k31": "v31"}}, {"k2": {"k21": "v21"}, "k3": {"k31": "v32"}},
     {"k1": "v1", "k2": {"k21": "v21"}, "k3": {"k31": "v32"}})
))
def test_merge_dicts(dict1, dict2, merged):
    _merge_dicts(dict1, dict2)
    assert dict1 == merged
