from contextlib import asynccontextmanager
from logging import WARNING

import pytest

from metricq_sink_nsca.subtask import Subtask, SubtaskProxy, subtask

from .conftest import step


@pytest.fixture
def endless_task():
    async def endless():
        while True:
            await step()

    return Subtask(endless, name="endless")


@asynccontextmanager
async def while_running(task: Subtask):
    task.start()
    await step()

    yield task

    task.cancel()
    await step()


@pytest.mark.asyncio
async def test_subtask_start_stop(endless_task):
    assert endless_task._task is None

    async with while_running(endless_task) as task:
        assert not task._task.done()
        save_task = task._task

    assert endless_task._task is None
    assert save_task.done()


@pytest.mark.asyncio
async def test_subtask_start_again(endless_task, caplog):
    async with while_running(endless_task) as task:
        task.start()
        await step()

    with caplog.at_level(WARNING, logger="metricq_sink_nsca.subtask"):
        assert "already started" in caplog.text


class SubtaskClass:
    @subtask
    async def endless(self):
        while True:
            await step()


@pytest.mark.asyncio
async def test_subtask_decorator_set_instance():
    test = SubtaskClass()

    assert "endless" not in test.__dict__, "Subtask set in instance before first access"
    task = test.endless
    assert isinstance(task, Subtask), "SubtaskProxy not dereferenced properly"
    assert "endless" in test.__dict__, "Subtask not created by proxy"
    assert (
        task is test.__dict__["endless"]
    ), "SubtaskProxy returned wrong Subtask object"


@pytest.mark.asyncio
async def test_subtask_decorator_proxy():
    proxy = SubtaskClass.endless
    assert isinstance(proxy, SubtaskProxy)
    assert proxy.attrname == "endless"


@pytest.mark.asyncio
async def test_subtask_decorator_start_stop():
    test = SubtaskClass()

    assert test.endless._task is None

    async with while_running(test.endless) as task:
        assert not task._task.done()
        save_task = task._task

    assert test.endless._task is None
    assert save_task.done()


def test_subtask_no_dunder_dict():
    class NoDunderDict:
        __slots__ = []

        @subtask
        async def impossible(self):
            pass

    with pytest.raises(TypeError):
        NoDunderDict().impossible


def test_subtask_read_only_dunder_dict():
    class RoDunderDict:
        class FrozenDict(dict):
            def __setitem__(self, index, value):
                raise TypeError()

        __dict__ = FrozenDict()

        @subtask
        async def impossible(self):
            pass

    with pytest.raises(RuntimeError):
        RoDunderDict().impossible


def test_subtask_dunder_doc():
    class Doc:
        @subtask
        async def foo(self):
            """foo"""
            pass

    assert Doc.foo.__doc__ == "foo"
