from logging import getLogger

import pytest
from metricq import Timedelta, Timestamp

from metricq_sink_nsca.state import State
from metricq_sink_nsca.state_cache import SoftFail, StateTransitionHistory

logger = getLogger(__name__)


@pytest.fixture
def empty_transition_history():
    return StateTransitionHistory(time_window=Timedelta.from_s(60))


@pytest.mark.parametrize(
    "max_fail_count, transitions",
    [
        (
            3,
            [
                (State.OK, State.OK),
                (State.WARNING, State.OK),
                (State.WARNING, State.OK),
                (State.WARNING, State.OK),
                (State.WARNING, State.WARNING),  # only trigger after the 4th bad state
                (State.OK, State.OK),
            ],
        ),
        (
            1,
            [
                (State.OK, State.OK),
                # Ignore a single bad state.
                (State.WARNING, State.OK),
                # Do not trigger `CRITICAL` (we should ignore a single state
                # worse than the preceeding one), but report `WARNING` as this
                # is still the second state that is not `OK`.
                (State.CRITICAL, State.WARNING),
                (State.WARNING, State.WARNING),
                (State.OK, State.OK),
            ],
        ),
        (
            0,
            [
                (State.OK, State.OK),
                (State.WARNING, State.WARNING),
                (State.OK, State.OK),
                (State.CRITICAL, State.CRITICAL),
            ],
        ),
    ],
)
def test_soft_fail(empty_transition_history, ticker, max_fail_count, transitions):
    soft_fail = SoftFail(max_fail_count)

    history = empty_transition_history
    history.insert(next(ticker), State.OK)

    ts: Timestamp
    state: State
    expected: State
    for ts, (state, expected) in zip(ticker, transitions):
        history.insert(ts, state)
        processed_state = soft_fail.process("metric", state, ts, history)
        logger.info(f"ts={ts}, state={state}, processed_state={processed_state}")
        assert processed_state == expected
