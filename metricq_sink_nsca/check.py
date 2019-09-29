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

from typing import Iterable, Dict, Optional, Coroutine, Set, NamedTuple

from metricq.types import Timedelta, Timestamp

from .value_check import ValueCheck
from .timeout_check import TimeoutCheck
from .plugin import Plugin, load as load_plugin
from .logging import get_logger
from .state import State
from .state_cache import StateCache

logger = get_logger(__name__)


class TvPair(NamedTuple):
    timestamp: Timestamp
    value: float


class CheckReport(NamedTuple):
    state: State
    message: str


class Check:
    def __init__(
        self,
        name: str,
        metrics: Iterable[str],
        value_constraints: Optional[Dict[str, float]],
        resend_interval: Timedelta,
        timeout: Optional[Timedelta] = None,
        on_timeout: Optional[Coroutine] = None,
        plugins: Optional[Dict[str, Dict]] = None,
        transition_debounce_window: Optional[Timedelta] = None,
    ):
        """Create value- and timeout-checks for a set of metrics

        :param name: The name of this check
        :param metrics: Iterable of names of metrics to monitor
        :param resend_interval: Minimum time interval at which this check should
            trigger reports, even if its overall state did not change.  This is
            useful for keeping the Centreon/Nagios host up-to-date and signaling
            that this passive check is not dead.
        :param value_constraints: Dictionary indicating warning and critical
            value ranges, see ValueCheck.  If omitted, this check does not care
            for which values its metrics report.
        :param timeout: If set, and a metric does not deliver values within
            this duration, run the callback on_timeout
        :param on_timeout: Callback to run when metrics do not deliver values
            in time, mandatory if timeout is given.
        :param plugins: A dictionary containing plugin configurations by name
        :param transition_debounce_window: Time window in which state
            transitions are debounced.
        """
        self._name = name
        self._metrics: Set[str] = set(metrics)

        self._state_cache = StateCache(
            metrics=self._metrics, transition_debounce_window=transition_debounce_window
        )
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
            self._timeout = timeout
            self._on_timeout_callback = on_timeout
            self._timeout_checks = {
                metric: TimeoutCheck(
                    self._timeout, self._get_on_timeout_callback(metric)
                )
                for metric in self._metrics
            }

        self._resend_interval: Timedelta = resend_interval
        self._last_report_triggered_time: Optional[Timestamp] = None

        self._plugins: Dict[str, Plugin] = dict()
        self._plugins_extra_metrics: Dict[str, Set[str]] = dict()
        if plugins is not None:
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
        self._extra_metrics: Set[str] = set().union(
            *self._plugins_extra_metrics.values()
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
        # in a while (dictated by self._resend_interval) we want to trigger a
        # report even though the overall state did not change.  This is a
        # compromise between always having an up-to-date report sent to the
        # host and not spamming the host with reports.
        now = Timestamp.now()
        is_stale = self._last_report_triggered_time is not None and (
            (self._last_report_triggered_time + self._resend_interval) <= now
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
                    details.append(f"{metric}: {detail}")

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
                    details.extend(sorted(metrics))

            header_line = ", ".join(header_line)
            details = "\n".join(details)
            message = f"{header_line}\n{details}"

        return (overall_state, message)

    def check_metric(
        self, metric: str, tv_pairs: Iterable[TvPair]
    ) -> Iterable[CheckReport]:
        if metric not in self._metrics:
            raise ValueError(f'Metric "{metric}" not known to check "{self._name}"')

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

            old_state = self._last_overall_state
            self._state_cache.update_state(metric, timestamp, state)
            if self._should_trigger_report():
                overall_state, message = self.format_overall_state()
                if old_state != overall_state:
                    logger.info(
                        f'Check "{self._name}" changed state: '
                        f"{old_state.name} -> {overall_state.name} "
                        f"(caused by {metric!r})"
                    )

                reports.append(CheckReport(state=overall_state, message=message))

        return reports

    def update_extra_metric(self, extra_metric: str, tv_pairs: Iterable[TvPair]):
        for timestamp, value in tv_pairs:
            for plugin_name in self._plugins:
                if extra_metric in self._plugins_extra_metrics[plugin_name]:
                    self._plugins[plugin_name].on_extra_metric(
                        extra_metric, timestamp, value
                    )

    def generate_reports(
        self, metric: str, tv_pairs: Iterable[TvPair]
    ) -> Iterable[CheckReport]:
        if metric in self._extra_metrics:
            self.update_extra_metric(extra_metric=metric, tv_pairs=tv_pairs)

        if metric in self._metrics:
            return self.check_metric(metric=metric, tv_pairs=tv_pairs)
        else:
            return list()

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
