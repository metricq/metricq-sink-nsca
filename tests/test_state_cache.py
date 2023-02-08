from dataclasses import dataclass
from logging import getLogger

import pytest
from metricq.types import Timedelta

from metricq_sink_nsca.state import State
from metricq_sink_nsca.state_cache import SoftFail, StateCache
from metricq_sink_nsca.value_check import ValueCheck

logger = getLogger(__name__)


@pytest.fixture
def value_check():
    return ValueCheck(warning_above=130, warning_below=120, critical_below=1)


@pytest.fixture
def soft_fail_cache():
    return StateCache(
        metrics=["publish.rate"],
        transition_debounce_window=Timedelta.from_string("1 day"),
        transition_postprocessor=SoftFail(max_fail_count=2),
    )


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
    for timestamp, context in zip(ticker, contexts):
        state = value_check.get_state(context.value)

        soft_fail_cache.update_state(metric, timestamp, state)

        overall_state = soft_fail_cache.overall_state()
        logger.info(
            f"metric={metric}, context={context}, "
            f"state={state}, overall_state={overall_state}"
        )

        assert state == context.state
        assert overall_state == context.postprocessed_state
