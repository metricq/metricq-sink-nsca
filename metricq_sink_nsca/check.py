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
from .plugin import Plugin, load as load_plugin
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


class Check:
    def __init__(
        self,
        name: str,
        metrics: Iterable[str],
        value_constraints: Optional[Dict[str, float]],
        timeout: Optional[str] = None,
        on_timeout: Optional[Coroutine] = None,
        plugins: Dict = {},
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
        self._last_overall_state = State.UNKNOWN

        self._value_check: Optional[ValueCheck] = ValueCheck(
            **value_constraints
        ) if value_constraints is not None else None
        self._timeout_checks: Optional[Dict[str, TimeoutCheck]] = None
        self._on_timeout_callback: Optional[Coroutine] = None

        self._timeout = None
        if timeout is not None:
            if on_timeout is None:
                raise ValueError("on_timeout callback is required if timeout is given")
            self._timeout = Timedelta.from_string(timeout)
            self._on_timeout_callback = on_timeout
            self._timeout_checks = {
                metric: TimeoutCheck(
                    self._timeout, self._get_on_timeout_callback(metric)
                )
                for metric in self._metrics
            }

        self._report_trigger_throttle_period = Timedelta.from_s(30)
        self._last_report_triggered_time = Timestamp(0)

        self._plugins: Dict[str, Plugin] = dict()
        self._plugins_extra_metrics: Dict[str, Set[str]] = dict()
        for name, config in plugins.items():
            logger.debug(f"Loading plugin {name!r}...")
            try:
                file = config["file"]
                plugin = load_plugin(
                    name=name,
                    file=file,
                    metrics=self._metrics,
                    config=config.get("config", {}),
                )
                self._plugins[name] = plugin
                self._plugins_extra_metrics[name] = plugin.extra_metrics()
                logger.info(
                    f"Loaded plugin {name!r} for check {self._name} from {file}"
                )
            except Exception:
                logger.exception(
                    f"Failed to load plugin {name!r} for check {self._name}"
                )
                raise
        self._extra_metrics: Set[str] = set.union(
            *(extra_metrics for extra_metrics in self._plugins_extra_metrics.values())
        )

    def _has_value_checks(self) -> bool:
        return self._value_check is not None

    def _has_timeout_checks(self) -> bool:
        return self._timeout_checks is not None

    def _should_trigger_report(self) -> bool:
        # Update overall state of this Check.
        new_state = self._state_cache.overall_state()
        old_state = self._last_overall_state
        self._last_overall_state = new_state

        # Has it been some time since we last triggered a report?  Every once
        # in a while (dictated by self._report_trigger_throttle_period) we want
        # to trigger a report even though the overall state did not change.
        # This is a compromise between always having an up-to-date report sent
        # to the host and not spamming the host with reports.
        now = Timestamp.now()
        is_stale = (
            self._last_report_triggered_time + self._report_trigger_throttle_period
            < now
        )

        should_trigger = new_state != old_state or is_stale
        if should_trigger:
            self._last_report_triggered_time = now

        return should_trigger

    def _get_on_timeout_callback(self, metric) -> Coroutine:
        async def on_timeout(timeout: Timedelta, last_timestamp: Optional[Timestamp]):
            logger.warning(f"Check {self._name!r}: {metric} timed out after {timeout}")
            self._state_cache.set_timed_out(metric, last_timestamp)
            if self._should_trigger_report():
                state, message = self.format_overall_state()
                await self._on_timeout_callback(
                    check_name=self._name, state=state, message=message
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

            timed_out = self._state_cache.timed_out
            if self._has_timeout_checks() and timed_out:
                header_line.append(
                    f"{len(timed_out)} metric(s) timed out after {self._timeout}"
                )
                for metric, last_timestamp in timed_out.items():
                    detail: str
                    if last_timestamp is None:
                        detail = "no values received"
                    else:
                        datestr = last_timestamp.datetime.isoformat(timespec="seconds")
                        detail = f"last value at {datestr}"
                    details.append(f"\t{metric}: {detail}")

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
            SNIP = "...\n<SOME METRICS OMITTED>"
            message = message[: MAX_LENGTH_MESSAGE - len(SNIP)]
            message += SNIP

        return (overall_state, message)

    def check_values(
        self, metric: str, tv_pairs: Iterable[Tuple[Timestamp, float]]
    ) -> Iterable[Tuple[State, str]]:
        is_extra_metric = metric in self._extra_metrics

        if metric not in self._metrics and not is_extra_metric:
            raise ValueError(f'Metric "{metric}" not known to check "{self._name}"')

        if is_extra_metric:
            for timestamp, value in tv_pairs:
                for plugin_name, plugin in self._plugins.items():
                    if metric in self._plugins_extra_metrics[plugin_name]:
                        plugin.on_extra_metric(metric, value, timestamp)
            return list()

        reports = list()
        for timestamp, value in tv_pairs:
            state = (
                self._value_check.get_state(value)
                if self._has_value_checks()
                else State.OK
            )

            # Update the state from plugins. If they yield different updated
            # states, use the most severe one as the new state of this metric
            # (values of the State enum are ordered by severity).
            state = max(
                (
                    plugin.check(metric, timestamp, value, state)
                    for plugin in self._plugins.values()
                ),
                key=lambda plugin_state: plugin_state.value,
                default=state,
            )

            self._state_cache.update_state(metric, state)
            if self._should_trigger_report():
                overall_state, message = self.format_overall_state()
                logger.debug(
                    f"Overall state changed to {overall_state!r} (caused by {metric!r})"
                )
                reports.append((overall_state, message))

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

    def extra_metrics(self) -> Iterable[str]:
        return self._extra_metrics

    def __contains__(self, metric: str) -> bool:
        return metric in self._metrics
