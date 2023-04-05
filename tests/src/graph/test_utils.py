# Copyright 2023 Petuum, Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License."

import pytest
from src.graph.utils.tycheck import has_shared_prefix
from src.graph.utils.classes import ValidationError, DeploymentError, collect_errors


@pytest.mark.parametrize("paths,expected", [(["/", "/"], True),
                                            (["/", "/a"], True),
                                            (["/a", "/a"], True),
                                            (["/a", "/a/b"], True),
                                            (["/a/b", "/a/b/"], True),
                                            (["/a/b", "/a"], True),
                                            (["/a/b", "/c"], False)])
def test_has_shared_prefix(paths, expected):
    assert has_shared_prefix(paths) == expected


def test_collect_errors():
    err1 = ValidationError({RuntimeError("Bad")})
    err2 = ValidationError({RuntimeError("Bad2")})

    try:
        collect_errors([err1, err2] + [RuntimeError(str(i)) for i in range(4)])
    except ValidationError as e:
        desired = set(
            [RuntimeError("Bad"),  RuntimeError("Bad2")] +
            [RuntimeError(str(i)) for i in range(4)])
        assert len(e.errors) == len(desired)
        for error in desired:
            assert str(error) in str(e.errors)
    try:
        collect_errors(
            [err1, err2, DeploymentError([RuntimeError('Extra bad')])] +
            [RuntimeError(str(i)) for i in range(4)])
    except RuntimeError as e:
        assert "controller error" in str(e)

    try:
        collect_errors([RuntimeError(str(i)) for i in range(4)], DeploymentError)
    except DeploymentError as e:
        assert len(e.errors) == 4

    try:
        collect_errors([RuntimeError(str(i)) for i in range(4)], ValidationError)
    except ValidationError as e:
        assert len(e.errors) == 4

    err1 = DeploymentError({RuntimeError("Bad")})
    err2 = DeploymentError({RuntimeError("Bad2")})

    try:
        collect_errors([err1, err2] + [RuntimeError(str(i)) for i in range(4)])
    except DeploymentError as e:
        desired = set(
            [RuntimeError("Bad"),  RuntimeError("Bad2")] +
            [RuntimeError(str(i)) for i in range(4)])
        assert len(e.errors) == len(desired)
        for error in desired:
            assert str(error) in str(e.errors)

    try:
        collect_errors([err1, err2], ValidationError)
    except RuntimeError as e:
        assert "controller error" in str(e)
