# Copyright 2023 Petuum, Inc. All Rights Reserved.
import unittest.mock

import asyncio
import kubernetes_asyncio as kubernetes
import pytest

import tests.src.graph.objects._test_graph_helper as helper

# The following patches are not needed because `conftest.py` was executed first and already
# used them to import the graph module. Putting them here anyways to be explicit.
with unittest.mock.patch.object(kubernetes, "client", unittest.mock.MagicMock()):
    with unittest.mock.patch.object(kubernetes, "config", unittest.mock.MagicMock()):
        from src.graph.objects.base_types import Metadata
        import src.graph.utils.deployment as deployment
        items_return = unittest.mock.MagicMock()
        items_return.items = [helper.generate_namespace("test1"),
                              helper.generate_namespace("test2"),
                              helper.generate_namespace("default-test-graph-2-c2")]


from src.graph.utils.classes import DeploymentError


@pytest.mark.asyncio
async def test_require_validated():
    @deployment.require_validated
    def test_function(obj, x):
        return x

    class test_class:
        def __init__(self):
            self._validated = False
            self.name = "foo"

        @property
        def validated(self):
            return self._validated

    obj = test_class()

    with pytest.raises(TypeError):
        assert 3 == test_function(obj, 3)

    obj._validated = True
    assert 3 == test_function(obj, 3)


@pytest.mark.asyncio
async def test_required_deployment():
    async def test_function_succ(x):
        return x

    async def test_function_fail(x):
        raise RuntimeError("bad")

    with pytest.raises(RuntimeError):
        await deployment.required_deploy(test_function_fail, 3)

    assert 3 == await deployment.required_deploy(test_function_succ, 3)


@pytest.mark.asyncio
async def test_optional_deployment():
    async def test_function_succ(x):
        return x

    async def test_function_fail(x):
        raise RuntimeError("bad")

    with pytest.raises(RuntimeError):
        await deployment.optional_deploy(
            test_function_fail,
            lambda x: "good" == str(x), 3)

    assert "bad" == str(await deployment.optional_deploy(
        test_function_fail,
        None, 3))

    assert "bad" == str(await deployment.optional_deploy(
        test_function_fail,
        lambda x: "bad" == str(x), 3))

    assert 3 == await deployment.optional_deploy(
        test_function_succ,
        lambda x: "bad" == str(x), 3)


@pytest.mark.asyncio
async def test_required_teardown():
    x = [0]

    async def test_side_effect():
        x[0] += 1

    async def test_side_effect_fail():
        x[0] += 1
        raise RuntimeError("bad")

    with pytest.raises(RuntimeError):
        await deployment.required_teardown(test_side_effect_fail)
    assert x[0] == 1

    await deployment.required_teardown(test_side_effect)
    assert x[0] == 2


@pytest.mark.asyncio
async def test_optional_teardown():
    x = [0]

    async def test_side_effect():
        x[0] += 1

    async def test_side_effect_fail():
        x[0] += 1
        raise RuntimeError("bad")

    with pytest.raises(RuntimeError):
        await deployment.optional_teardown(
            test_side_effect_fail,
            lambda x: "good" == str(x))

    assert x[0] == 1

    assert "bad" == str(await deployment.optional_teardown(
        test_side_effect_fail,
        None))

    assert x[0] == 2

    assert "bad" == str(await deployment.optional_teardown(
        test_side_effect_fail,
        lambda x: "bad" == str(x)))

    assert x[0] == 3
    await deployment.optional_teardown(
        test_side_effect,
        lambda x: "bad" == str(x))


@pytest.mark.asyncio
async def test_subprocess_succeed():
    command_succ = ["bash", "-c", "echo 'test'"]

    metadata = Metadata("testnamespace", "testname", "testuid")

    retcode, stdout, stderr = await deployment.required_subprocess(
        metadata, False, None, *command_succ)
    assert retcode == 0
    assert stdout == "test\n"
    assert not stderr

    stdout, stderr = await deployment.optional_subprocess(
        metadata, False, None, *command_succ)
    assert stdout == "test\n"
    assert not stderr


@pytest.mark.asyncio
async def test_subprocess_fail():
    command_fail = ["bash", "-c", "cd /no/such/directory"]

    metadata = Metadata("testnamespace", "testname", "testuid")

    with pytest.raises(DeploymentError) as e:
        retcode, stdout, stderr = await deployment.required_subprocess(
            metadata, False, None, *command_fail)
    assert "No such file or directory" in str(e)

    err = await deployment.optional_subprocess(metadata, False, None, *command_fail)
    assert isinstance(err, DeploymentError)
    assert "No such file or directory" in str(e)


@pytest.mark.asyncio
async def test_subprocess_cancel():
    command_timeout = ["sleep", "1000"]

    metadata = Metadata("testnamespace", "testname", "testuid")

    x = [0]

    async def callback():
        x[0] += 1

    def callback_immediate():
        x[0] += 1

    task = asyncio.create_task(deployment.required_subprocess(
        metadata, True, callback, *command_timeout))

    # Yield control to the task to allow for the try/except asyncio.CancelledError context to start
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert x[0] == 1

    task = asyncio.create_task(deployment.required_subprocess(
        metadata, True, callback, *command_timeout))

    # Yield control to the task to allow for the try/except asyncio.CancelledError context to start
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert x[0] == 2
