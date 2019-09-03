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

from typing import Iterable, Dict, Optional, Coroutine, Set, Tuple

from metricq.types import Timedelta, Timestamp
from aionsca import State
from aionsca.report import MAX_LENGTH_MESSAGE

from .value_check import ValueCheck
from .timeout_check import TimeoutCheck
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

    def update_state(self, metric: str, state: State) -> bool:
        """Update the cached state of a metric
        """
        last_state: State = None
        for prev_state, metrics in self._by_state.items():
            if metric in metrics:
                metrics.remove(metric)
                last_state = prev_state
                break
        else:
            raise ValueError(
                f"StateCache not setup to track state of metric {metric!r}"
            )

        try:
            self._by_state[state].add(metric)
        except KeyError:
            raise ValueError(f"Not a valid state: {state!r} ({type(state).__name__})")

        return last_state != state

    def __repr__(self):
        return f"StateCache(categories={self._categories})"

    def overall_state(self) -> State:
        """Return the most severe state of any cached metric

        If any of the contained metrics are critical, return State.CRITICAL,
        if any are warning, return State.WARNING etc.

        Should any metrics be in an unknown state, return State.UNKNOWN. This
        happens if they were never updated via update_state().
        """
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


class Check:
    def __init__(
        self,
        name: str,
        metrics: Iterable[str],
        value_constraints: Optional[Dict[str, float]],
        timeout: Optional[str] = None,
        on_timeout: Optional[Coroutine] = None,
    ):
        """Create value- and timeout-checks for a set of metrics

        :param name: The name of this check
        :param metrics: Iterable of names of metrics to monitor
        :param value_constraints: Dictionary indicating warning and critical
            value ranges, see ValueCheck.  If omitted, this check does not care
            for which values its metrics report.
        :param timeout: If set, and a metric does not deliver values within
            this duration, run the callback on_timeout
        :param on_timeout: Callback to run when metrics do not deliver values
            in time, mandatory if timeout is given.
        """
        self._name = name
        self._metrics: Set[str] = set(metrics)

        self._state_cache = StateCache(self._metrics)

        self._value_check: Optional[ValueCheck] = ValueCheck(
            **value_constraints
        ) if value_constraints is not None else None
        self._timeout_checks: Optional[Dict[str, TimeoutCheck]] = None
        self._on_timeout_callback: Optional[Coroutine] = None

        if timeout is not None:
            if on_timeout is None:
                raise ValueError("on_timeout callback is required if timeout is given")
            self._on_timeout_callback = on_timeout
            self._timeout_checks = {
                metric: TimeoutCheck(
                    Timedelta.from_string(timeout),
                    self._get_on_timeout_callback(metric),
                )
                for metric in self._metrics
            }

    def _has_value_checks(self) -> bool:
        return self._value_check is not None

    def _has_timeout_checks(self) -> bool:
        return self._timeout_checks is not None

    def _get_on_timeout_callback(self, metric) -> Coroutine:
        async def on_timeout(timeout, last_timestamp):
            await self._on_timeout_callback(
                check_name=self._name,
                metric=metric,
                timeout=timeout,
                last_timestamp=last_timestamp,
            )

        return on_timeout

    def format_overall_state(self) -> (State, str):
        overall_state = self._state_cache.overall_state()

        message: str
        if overall_state == State.OK:
            message = "All metrics are OK"
        else:
            header_line = list()
            details = list()

            for state in (State.UNKNOWN, State.CRITICAL, State.WARNING):
                name = state.name
                metrics = self._state_cache[state]
                if len(metrics):
                    header_part = f"{len(metrics)} metric(s) are {name}"
                    if state is not State.UNKNOWN and self._has_value_checks():
                        abnormal_range = self._value_check.range_by_state(state)
                        header_part += f" ({abnormal_range!s})"

                    header_line.append(header_part)
                    details.append(f"{name}:")
                    for metric in metrics:
                        details.append(f"\t{metric}")

            header_line = ", ".join(header_line)
            details = "\n".join(details)
            message = f"{header_line}\n{details}"

        if len(message) > MAX_LENGTH_MESSAGE:
            logger.warning(f"Details exceed maximum message length!")
            SNIP = "\n...\n<SOME METRICS OMITTED>"
            message = message[: MAX_LENGTH_MESSAGE - len(SNIP)]
            message += SNIP

        return (overall_state, message)

    def check_values(
        self, metric: str, values: Iterable[float]
    ) -> Iterable[Tuple[State, str]]:
        if not self._has_value_checks():
            return list()

        if metric not in self._metrics:
            raise ValueError(f'Metric "{metric}" not known to check "{self._name}"')

        reports = list()
        for value in values:
            state = self._value_check.get_state(value)
            changed = self._state_cache.update_state(metric, state)
            if changed:
                logger.debug(f"State for {metric!r} changed to {state!r}")
                state, message = self.format_overall_state()
                reports.append((state, message))

        return reports

    async def bump_timeout_check(self, metric: str, timestamp: Timestamp) -> None:
        if self._has_timeout_checks():
            try:
                self._timeout_checks[metric].bump(timestamp)
            except KeyError:
                raise ValueError(f'Metric "{metric}" not known to check')

    def cancel_timeout_checks(self) -> None:
        if self._has_timeout_checks():
            for check in self._timeout_checks.values():
                check.cancel()

    def metrics(self) -> Iterable[str]:
        return self._metrics

    def __contains__(self, metric: str) -> bool:
        return metric in self._metrics
