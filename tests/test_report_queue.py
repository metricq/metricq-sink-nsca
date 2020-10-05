from typing import Iterator, List, TypeVar

import pytest
from metricq.types import Timedelta

from metricq_sink_nsca.report_queue import Report, ReportQueue
from metricq_sink_nsca.state import State

pytestmark = pytest.mark.asyncio

_T = TypeVar("T")


def take(it: Iterator[_T], num: int) -> List[_T]:
    return [item for item, _ in zip(it, range(num))]


@pytest.fixture
def reports():
    def gen() -> Iterator[Report]:
        i = 0
        while True:
            yield Report(
                service=f"service.{i}",
                state=State.OK,
                message=f"message.{i}",
            )
            i += 1

    return gen()


@pytest.fixture
def tick() -> Timedelta:
    return Timedelta.from_s(0.1)


async def test_batch_from_put_before(reports, tick):
    reports = take(reports, 5)
    queue = ReportQueue()

    for r in reports:
        queue.put(r)

    async for expected in queue.batch(tick):
        assert expected == reports.pop(0)


async def test_empty_batch_from_empty_queue(tick):
    queue = ReportQueue()

    assert [r async for r in queue.batch(tick)] == []


async def test_empty_batch_then_some(reports, tick):
    queue = ReportQueue()

    assert [r async for r in queue.batch(tick)] == []

    batch = take(reports, 5)

    for r in batch:
        queue.put(r)

    assert [r async for r in queue.batch(tick)] == batch
