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

from asyncio import sleep
from typing import Dict, Iterable, NamedTuple, Optional, Set

from metricq.types import Timedelta, Timestamp

from .logging import get_logger
from .plugin import Plugin
from .plugin import load as load_plugin
from .report_queue import Report, ReportQueue
from .state import State
from .state_cache import (
    IgnoreShortTransitions,
    SoftFail,
    StateCache,
    TransitionDebounce,
    TransitionPostprocessor,
)
from .subtask import subtask
from .timeout_check import TimeoutCallback, TimeoutCheck
from .value_check import ValueCheck

logger = get_logger(__name__)


class TvPair(NamedTuple):
    timestamp: Timestamp
    value: float


class Check:
    def __init__(
        self,
        name: str,
        metrics: Iterable[str],
        report_queue: ReportQueue,
        value_constraints: Optional[Dict[str, float]],
        resend_interval: Timedelta,
        timeout: Optional[Timedelta] = None,
        plugins: Optional[Dict[str, Dict]] = None,
        transition_debounce_window: Optional[Timedelta] = None,
        transition_postprocessing: Optional[Dict] = None,
    ):
        """Create value- and timeout-checks for a set of metrics

        :param name: The name of this check
        :param metrics: Iterable of names of metrics to monitor
        :param report_queue: Queue to put generated reports into
        :param resend_interval: Minimum time interval at which this check should
            trigger reports, even if its overall state did not change.  This is
            useful for keeping the Centreon/Nagios host up-to-date and signaling
            that this passive check is not dead.
        :param value_constraints: Dictionary indicating warning and critical
            value ranges, see ValueCheck.  If omitted, this check does not care
            for which values its metrics report.
        :param timeout: If set, and a metric does not deliver values within
            this duration, a report of 'CRITICAL' severity is put into the queue.
        :param plugins: A dictionary containing plugin configurations by name
        :param transition_debounce_window: Time window in which state
            transitions are debounced.
        """
        self._name = name
        self._metrics: Set[str] = set(metrics)
        self._report_queue = report_queue

        transition_postprocessor: Optional[TransitionPostprocessor] = None

        if transition_postprocessing is not None:
            POSTPROCESSORS = {
                "debounce": TransitionDebounce,
                "ignore_short_transitions": IgnoreShortTransitions,
                "soft_fail": SoftFail,
            }
            try:
                selected = transition_postprocessing.get("type", "debounce")
                transition_postprocessor = POSTPROCESSORS[selected](
                    **transition_postprocessing
                )
            except KeyError:
                raise ValueError(
                    f"Unknown transition postprocessor {selected!r} specified"
                )

        self._state_cache = StateCache(
            metrics=self._metrics,
            transition_debounce_window=transition_debounce_window,
            transition_postprocessor=transition_postprocessor,
        )
        self._last_overall_state = State.UNKNOWN

        self._value_check: Optional[ValueCheck] = (
            ValueCheck(**value_constraints) if value_constraints is not None else None
        )
        self._timeout_checks: Optional[Dict[str, TimeoutCheck]] = None

        self._timeout: Optional[Timedelta] = timeout
        if timeout is not None:
            self._timeout_checks = {
                metric: TimeoutCheck(
                    self._timeout,
                    self._get_on_timeout_callback(metric),
                    name=metric,
                )
                for metric in self._metrics
            }

        self._resend_interval: Timedelta = resend_interval

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

    def _trigger_report(self, force: bool = False) -> None:
        # Update overall state of this Check.
        new_state = self._state_cache.overall_state()
        old_state = self._last_overall_state
        self._last_overall_state = new_state

        if force or new_state != old_state:
            if force:
                logger.debug(
                    'Check "{}" is {} (forced update)', self._name, new_state.name
                )
            else:
                logger.debug(
                    'Check "{}" changed state: {} -> {}',
                    self._name,
                    old_state.name,
                    new_state.name,
                )

            message = self.format_report_message(new_state)
            report = Report(service=self._name, state=new_state, message=message)
            self._report_queue.put(report)

    def _trigger_exception_report(self, e: Exception):
        message = [f"Unhandled exception: {e}"]

        cause = e.__cause__

        while cause is not None:
            message.append(f"caused by: {cause}")
            cause = cause.__cause__

        self._report_queue.put(
            Report(service=self._name, state=State.CRITICAL, message="\n".join(message))
        )

    def _get_on_timeout_callback(self, metric) -> TimeoutCallback:
        def on_timeout(timeout: Timedelta, last_timestamp: Optional[Timestamp]):
            logger.warning(f"Check {self._name!r}: {metric} timed out after {timeout}")
            self._state_cache.set_timed_out(metric, last_timestamp)
            self._trigger_report()

        return on_timeout

    def format_report_message(self, overall_state: State) -> str:
        if overall_state == State.OK:
            return "All metrics are OK"
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
            return f"{header_line}\n{details}"

    def check_metric(self, metric: str, tv_pairs: Iterable[TvPair]) -> None:
        if metric not in self._metrics:
            raise ValueError(f'Metric "{metric}" not known to check "{self._name}"')

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

            self._state_cache.update_state(metric, timestamp, state)
            self._trigger_report()

    def update_extra_metric(self, extra_metric: str, tv_pairs: Iterable[TvPair]):
        for timestamp, value in tv_pairs:
            for plugin_name in self._plugins:
                if extra_metric in self._plugins_extra_metrics[plugin_name]:
                    self._plugins[plugin_name].on_extra_metric(
                        extra_metric, timestamp, value
                    )

    # TODO: rename
    def check(self, metric: str, tv_pairs: Iterable[TvPair]) -> None:
        try:
            if metric in self._extra_metrics:
                self.update_extra_metric(extra_metric=metric, tv_pairs=tv_pairs)

            if metric in self._metrics:
                self.check_metric(metric=metric, tv_pairs=tv_pairs)
        except Exception as e:
            logger.exception(
                "Unhandled exception when checking values for {!r}", metric
            )
            self._trigger_exception_report(e)

    def bump_timeout_check(self, metric: str, timestamp: Timestamp) -> None:
        if self._has_timeout_checks():
            try:
                self._timeout_checks[metric].bump(timestamp)
            except KeyError:
                raise ValueError(f'Metric "{metric}" not known to check')

    @subtask
    async def heartbeat(self) -> None:
        while True:
            await sleep(self._resend_interval.s)
            logger.debug('Sending heartbeat for check "{}"', self._name)
            self._trigger_report(force=True)

    def start(self) -> None:
        if self._has_timeout_checks():
            for check in self._timeout_checks.values():
                check.start()

        self.heartbeat.start()

    def cancel(self) -> None:
        if self._has_timeout_checks():
            for check in self._timeout_checks.values():
                check.cancel()

        self.heartbeat.cancel()

    def metrics(self) -> Iterable[str]:
        return self._metrics

    def extra_metrics(self) -> Iterable[str]:
        return self._extra_metrics

    def __contains__(self, metric: str) -> bool:
        return metric in self._metrics
