# Copyright 2023 Petuum, Inc. All Rights Reserved.
import pytest
from tests.helpers.constants import REGISTRY_URL


@pytest.fixture(scope="session")
def registry_url():
    return REGISTRY_URL
