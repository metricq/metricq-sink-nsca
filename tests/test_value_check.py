import pytest

from metricq_sink_nsca.state import State
from metricq_sink_nsca.value_check import ValueCheck


@pytest.fixture
def value_check():
    return ValueCheck(
        warning_below=0.05,
        warning_above=0.95,
        critical_below=0.0,
        critical_above=1.0,
        ignore=[-0.42],
    )


@pytest.mark.parametrize(
    "value, expected_state",
    [
        (-0.1, State.CRITICAL),
        (0.0, State.WARNING),
        (0.05, State.OK),
        (0.95, State.OK),
        (1.0, State.WARNING),
        (1.1, State.CRITICAL),
        (-0.42, State.OK),
    ],
)
def test_value_check_get_state(value_check, value, expected_state):
    assert value_check.get_state(value) == expected_state


def test_value_check_empty_config():
    """Omitting any constraints from the configuration disables value checks.

    The `from_config` method should return `None` in this case.
    """
    assert ValueCheck.from_config(config={}) is None
