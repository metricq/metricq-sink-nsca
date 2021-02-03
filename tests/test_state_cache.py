from dataclasses import dataclass
from logging import WARNING, getLogger

import pytest
from metricq.types import Timedelta, Timestamp
from pytest import LogCaptureFixture

from metricq_sink_nsca.state import State
from metricq_sink_nsca.state_cache import SoftFail, StateCache
from metricq_sink_nsca.value_check import ValueCheck

from tests.conftest import Ticker

logger = getLogger(__name__)


@pytest.fixture
def value_check():
    return ValueCheck(warning_above=130, warning_below=120, critical_below=1)


@pytest.fixture
def soft_fail_cache() -> StateCache:
    return StateCache(
        metrics=["publish.rate"],
        transition_debounce_window=Timedelta.from_string("1 day"),
        transition_postprocessor=SoftFail(max_fail_count=2),
    )


@pytest.fixture
def state_cache() -> StateCache:
    return StateCache(metrics=["publish.rate"])


@dataclass
class Context:
    value: int
    state: State
    postprocessed_state: State


@pytest.mark.parametrize(
    "metric, ticker, contexts",
    [
        (
            "publish.rate",
            "1min",
            [
                Context(125, State.OK, State.OK),
                Context(125, State.OK, State.OK),
                Context(125, State.OK, State.OK),
                Context(133, State.WARNING, State.OK),
                Context(115, State.WARNING, State.OK),
                Context(125, State.OK, State.OK),
            ],
        )
    ],
    indirect=["ticker"],
)
def test_state_cache(value_check, soft_fail_cache, metric, ticker, contexts):
    soft_fail_cache.update_state(metric, next(ticker), State.OK)
    for (timestamp, context) in zip(ticker, contexts):
        state = value_check.get_state(context.value)

        soft_fail_cache.update_state(metric, timestamp, state)

        overall_state = soft_fail_cache.overall_state()
        logger.info(
            f"metric={metric}, context={context}, "
            f"state={state}, overall_state={overall_state}"
        )

        assert state == context.state
        assert overall_state == context.postprocessed_state


def test_update_nonmonotonic(state_cache: StateCache, ticker: Ticker):
    ts: Timestamp = next(ticker)
    state_cache.update_state("publish.rate", timestamp=ts, state=State.OK)

    with pytest.raises(ValueError):
        state_cache.update_state("publish.rate", timestamp=ts, state=State.OK)


@pytest.mark.parametrize("delta", [Timedelta(0), Timedelta(42)])
def test_update_nonmonotonic_ignore(
    delta: Timedelta,
    ticker: Ticker,
    caplog: LogCaptureFixture,
):
    metric = "publish.rate"
    state_cache = StateCache(metrics=[metric], ignore_update_errors=True)
    epoch: Timestamp = next(ticker)

    state_cache.update_state(metric, timestamp=epoch, state=State.OK)
    state_cache.update_state(metric, timestamp=next(ticker), state=State.OK)

    with caplog.at_level(WARNING):
        non_monotonic_ts: Timestamp = epoch - delta  # type: ignore
        state_cache.update_state(metric, timestamp=non_monotonic_ts, state=State.OK)

        assert f"Failed to update state history of {metric!r}" in caplog.text
