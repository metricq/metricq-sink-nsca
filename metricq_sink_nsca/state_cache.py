# metricq-sink-nsca
# Copyright (C) 2019 ZIH, Technische Universitaet Dresden, Federal Republic of Germany
#
# All rights reserved.
#
# This file is part of metricq.
#
# metricq is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# metricq is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with metricq.  If not, see <http://www.gnu.org/licenses/>.

from typing import Dict, Optional, Set

from metricq.types import Timestamp
from aionsca import State

from .logging import get_logger

logger = get_logger(__name__)


class StateCache:
    def __init__(self, *metrics):
        self._by_state: Dict[State, Set[str]] = {
            State.OK: set(),
            State.WARNING: set(),
            State.CRITICAL: set(),
            State.UNKNOWN: set(*metrics),
        }
        self._timed_out: Dict[str, Optional[Timestamp]] = dict()

    def update_state(self, metric: str, state: State):
        """Update the cached state of a metric

        This implicitly marks a metric as not being timed out.
        """
        self._timed_out.pop(metric, None)
        for metrics in self._by_state.values():
            if metric in metrics:
                metrics.remove(metric)
                break
        else:
            raise ValueError(
                f"StateCache not setup to track state of metric {metric!r}"
            )

        try:
            self._by_state[state].add(metric)
        except KeyError:
            raise ValueError(f"Not a valid state: {state!r} ({type(state).__name__})")

    def set_timed_out(self, metric: str, last_timestamp: Optional[Timestamp]):
        self._timed_out[metric] = last_timestamp

    def __repr__(self):
        return f"StateCache(by_state={self._by_state}, timed_out={self._timed_out})"

    def overall_state(self) -> State:
        """Return the most severe state of any cached metric

        If any of the contained metrics are critical, return State.CRITICAL,
        if any are warning, return State.WARNING etc.

        Should any metrics be in an unknown state, return State.UNKNOWN. This
        happens if they were never updated via update_state().
        """
        if self._timed_out:
            return State.CRITICAL

        if self._by_state[State.UNKNOWN]:
            return State.UNKNOWN
        elif self._by_state[State.CRITICAL]:
            return State.CRITICAL
        elif self._by_state[State.WARNING]:
            return State.WARNING
        elif self._by_state[State.OK]:
            return State.OK
        else:
            return State.UNKNOWN

    def __getitem__(self, state: State) -> Set[str]:
        return self._by_state[state]

    @property
    def timed_out(self) -> Dict[str, Optional[Timestamp]]:
        return self._timed_out
