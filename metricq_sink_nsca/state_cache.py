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

from typing import Dict, Optional, Set, List, Iterable
from dataclasses import dataclass

from metricq.types import Timestamp, Timedelta

from .state import State
from .logging import get_logger

logger = get_logger(__name__)


@dataclass
class StateTransition:
    time: Timestamp
    state: State


class StateTransitionHistory:
    def __init__(self, debounce_window: Optional[Timedelta]):
        self._transitions: List[StateTransition] = list()
        self._debounce_window: Optional[Timedelta] = debounce_window

    def insert(self, time: Timestamp, state: State):
        transition = StateTransition(time, state)
        self._transitions.append(transition)

        # prune old transitions
        if self._debounce_window is not None:
            for i in range(len(self._transitions[:-1])):
                if self._transitions[i + 1].time + self._debounce_window >= time:
                    del self._transitions[:i]
                    break
        else:
            del self._transitions[:-1]

    def current_time_window(self) -> Optional[Timedelta]:
        if not self._transitions:
            return None
        else:
            return self._transitions[-1].time - self._transitions[0].time

    def state_prevalences(self) -> Optional[Dict[State, float]]:
        time_window = self.current_time_window()
        if time_window is None or time_window.ns == 0:
            return None

        assert self._transitions
        prevalences = {state: Timedelta(0) for state in State}
        last_transition = self._transitions[0]
        for transition in self._transitions[1:]:
            prevalences[transition.state] += transition.time - last_transition.time
            last_transition = transition

        try:
            return {
                state: duration.ns / time_window.ns
                for state, duration in prevalences.items()
            }
        except ZeroDivisionError:
            return None

    def __repr__(self):
        return f"{type(self).__name__}(window={self._time_window}, current_window={self.current_time_window()}, transitions={self._transitions})"


class StateCache:
    def __init__(
        self,
        metrics: Iterable[str],
        transition_debounce_window: Optional[Timedelta] = None,
    ):
        metrics = tuple(metrics)
        logger.debug(f"Initializing StateCache for metrics {metrics}")
        self._transition_histories: Dict[str, StateTransitionHistory] = {
            metric: StateTransitionHistory(time_window=transition_debounce_window)
            for metric in metrics
        }
        self._by_state: Dict[State, Set[str]] = {
            State.OK: set(),
            State.WARNING: set(),
            State.CRITICAL: set(),
            State.UNKNOWN: set(metrics),
        }
        self._timed_out: Dict[str, Optional[Timestamp]] = dict()
        logger.debug(repr(self))

    def update_state(self, metric: str, timestamp: Timestamp, state: State):
        """Update the cached state of a metric

        This implicitly marks a metric as not being timed out.
        """
        try:
            metric_history = self._transition_histories[metric]
        except KeyError:
            raise ValueError(
                f"{type(self).__name__} not set up to track state of metric {metric}"
            )

        metric_history.insert(time=timestamp, state=state)
        logger.debug(f"history({metric}): {metric_history}")
        prevalences = metric_history.state_prevalences()
        logger.debug(f"prevalences: {(prevalences or {}).items()}")

        if prevalences is None:
            prevalent_state = state
        else:
            prevalent_state = max(prevalences, key=lambda state: prevalences[state])

        self._update_cache(metric, prevalent_state)

    def _update_cache(self, metric: str, state: State):
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
        return f"StateCache(transitions={self._transition_histories}, timed_out={self._timed_out})"

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
