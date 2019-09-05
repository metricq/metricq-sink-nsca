from metricq import Timestamp
from aionsca import State

from typing import Set
from logging import getLogger
from math import inf

logger = getLogger(__name__)


class IgnoreValueRangePlugin:
    def __init__(self, low, high):
        self.low = low
        self.high = high

    def check(
        self,
        metric: str,
        timestamp: Timestamp,
        value: float,
        current_state: State,
        *_args,
        **_kwargs,
    ) -> State:
        if self.low <= value <= self.high:
            logger.info(
                f"{metric!r} @ {timestamp}: ignoring {value} in [{self.low}, {self.high}]"
            )
            return State.OK
        else:
            return current_state

    def extra_metrics(self):
        # no extra metrics required to determine if value lies withing ignored range
        return ()

    def on_extra_metric(self, *_args, **_kwargs):
        pass


def get_plugin(_name: str, config: dict, _metrics: Set[str]):
    low = config.get("low", -inf)
    high = config.get("high", inf)
    return IgnoreValueRangePlugin(low, high)
