import asyncio
from contextlib import asynccontextmanager
from typing import cast

import pytest
from metricq.types import Timedelta, Timestamp

from metricq_sink_nsca.logging import get_logger
from metricq_sink_nsca.timeout_check import TimeoutCallback, TimeoutCheck

from .conftest import sleep, step

logger = get_logger(__name__)

pytestmark = pytest.mark.asyncio


class Callback(TimeoutCallback):
    def __init__(self):
        self.called = False
        self.timeout = None
        self.last_timestamp = None

    def __call__(self, *, timeout, last_timestamp):
        self.called = True
        self.timeout = timeout
        self.last_timestamp = last_timestamp
        logger.info("Callback called: {!r}", self)

    def __repr__(self):
        return f"<Callback: called={self.called!r}, timeout={self.timeout!r}, last_timestamp={self.last_timestamp!r}>"


@pytest.fixture
def callback() -> Callback:
    return Callback()


@pytest.fixture
def timeout() -> Timedelta:
    return Timedelta.from_ms(100)


@asynccontextmanager
async def run(timeout_check: TimeoutCheck):
    try:
        timeout_check.start()
        await step()
        yield timeout_check
    finally:
        await asyncio.wait_for(timeout_check.stop(), timeout=1.0)


@pytest.fixture(scope="function")
async def timeout_check(
    timeout,
    callback,
) -> TimeoutCheck:
    async with run(TimeoutCheck(timeout=timeout, on_timeout=callback)) as timeout_check:
        yield timeout_check


async def test_timeout_check_no_bump(timeout_check):
    await sleep(timeout_check._timeout + Timedelta.from_ms(10))

    callback = timeout_check._timeout_callback
    assert callback.called
    assert callback.last_timestamp is None
    assert callback.timeout == timeout_check._timeout


async def test_timeout_check_bump_once(timeout_check: TimeoutCheck):
    now = Timestamp.now()
    timeout_check.bump(now)

    await step()

    callback = cast(Callback, timeout_check._timeout_callback)
    assert not callback.called
    assert timeout_check._last_timestamp == now


async def test_timeout_check_no_callback_after_cancel(timeout):
    class CallOnce(Callback):
        def __init__(self):
            self.called_before = False
            super().__init__()

        def __call__(self, *, timeout, last_timestamp):
            assert not self.called_before
            super().__call__(timeout=timeout, last_timestamp=last_timestamp)
            self.called_before = True

    timeout_check = TimeoutCheck(timeout=timeout, on_timeout=CallOnce())

    timeout_check.start()
    await sleep(timeout_check._timeout + Timedelta.from_ms(10))

    timeout_check.cancel()
    await sleep(timeout_check._timeout + Timedelta.from_ms(10))
