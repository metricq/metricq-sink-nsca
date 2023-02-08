import logging
from logging import getLogger

import pytest
from metricq.types import Timedelta, Timestamp

from metricq_sink_nsca.state import State
from metricq_sink_nsca.state_cache import StateTransitionHistory

logger = getLogger(__name__)


@pytest.fixture
def empty_history():
    return StateTransitionHistory(None)


def test_history_set_epoch(empty_history):
    # An empty StateTransitionHistory should not have an epoch set
    assert empty_history.epoch is None

    # The first transition to be inserted is discarded, only its timestamp is
    # kept as the epoch value for this history.
    empty_history.insert(Timestamp(0), State.OK)
    assert empty_history.epoch == Timestamp(0)
    assert not empty_history.transitions


@pytest.fixture
def history_with_epoch_set():
    history = StateTransitionHistory(None)
    history.insert(Timestamp(0), State.OK)
    return history


def test_history_insert_with_epoch_set(history_with_epoch_set):
    # Inserting a transition into a history with an epoch already set should
    # make that transition the most recent transition of that history.
    ts = history_with_epoch_set.epoch + Timedelta.from_s(1)
    history_with_epoch_set.insert(ts, State.OK)

    assert history_with_epoch_set.transitions[-1].time == ts


def test_history_monotonous(history_with_epoch_set):
    ts = history_with_epoch_set.epoch
    for delta in (Timedelta.from_s(1), Timedelta.from_string("20s")):
        new_ts = ts + delta
        history_with_epoch_set.insert(new_ts, State.OK)

        assert history_with_epoch_set.transitions[-1].time == new_ts


@pytest.mark.parametrize(
    "delta",
    [
        Timedelta(0),
        Timedelta.from_s(-1),
    ],
)
def test_history_non_monotonous(history_with_epoch_set, delta, caplog):
    ts = history_with_epoch_set.epoch + Timedelta.from_s(1)
    history_with_epoch_set.insert(ts, State.OK)

    next_ts = ts + delta
    with caplog.at_level(logging.WARNING):
        history_with_epoch_set.insert(next_ts, State.OK)
        assert "Times of state transitions must be strictly increasing" in caplog.text


@pytest.mark.parametrize(
    "ticker", [Timedelta.from_string("30s"), Timedelta(1)], indirect=True
)
@pytest.mark.parametrize("expected_history_items", [0, 1, 3])
def test_history_length(ticker, expected_history_items):
    history = StateTransitionHistory(
        time_window=ticker.delta * (expected_history_items + 1)
    )

    epoch = next(ticker)
    history.insert(epoch, State.OK)

    assert history.epoch == epoch

    for timestamp, _ in zip(ticker, range(expected_history_items)):
        history.insert(timestamp, State.OK)

    logger.info(f"history={history!r}")
    assert len(history.transitions) == expected_history_items
