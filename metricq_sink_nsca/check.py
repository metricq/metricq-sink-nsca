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

from typing import Iterable, Dict, Optional, Coroutine, Set, NamedTuple, Tuple

from metricq.types import Timedelta, Timestamp
from aionsca import State as Status

from .value_check import ValueCheck
from .timeout_check import TimeoutCheck
from .logging import get_logger

logger = get_logger(__name__)

_StatusCollection = Dict[str, float]


class _StatusCacheCategories(NamedTuple):
    ok: _StatusCollection = dict()
    warning: _StatusCollection = dict()
    critical: _StatusCollection = dict()


class StatusCache:
    def __init__(self, *metrics: str):
        self._unknown: Set[str] = set(*metrics)
        self._categories: _StatusCacheCategories = _StatusCacheCategories()

    def update_status(self, metric: str, value: float, status: Status):
        """Update the cached status of a metric
        """
        was_known = any(
            category.pop(metric, None) is not None for category in self._categories
        )

        was_unknown = metric in self._unknown
        self._unknown.discard(metric)

        assert was_known or was_unknown

        if status == Status.OK:
            self._categories.ok[metric] = value
        elif status == Status.WARNING:
            self._categories.warning[metric] = value
        elif status == Status.CRITICAL:
            self._categories.critical[metric] = value
        else:
            raise ValueError(f"Not a status: {status!r}")

    def __repr__(self):
        return f"StatusCache(unknown={self._unknown}, categories={self._categories})"

    def overall_status(self) -> Optional[Status]:
        """Return the most severe status of any cached metric

        If any of the contained metrics are critical, return Status.CRITICAL,
        if any are warning, return Status.WARNING etc.

        Should all metrics be in an unknown state, return None. This happens if
        they were never updated via update_status().
        """
        if self._categories.critical:
            return Status.CRITICAL
        elif self._categories.warning:
            return Status.WARNING
        elif self._categories.ok:
            return Status.OK
        else:
            return None

    @property
    def ok(self) -> _StatusCollection:
        return self._categories.ok

    @property
    def warning(self) -> _StatusCollection:
        return self._categories.warning

    @property
    def critical(self) -> _StatusCollection:
        return self._categories.critical


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

        self._status_cache = StatusCache(self._metrics)

        self._value_checks: Optional[Dict[str, ValueCheck]] = None
        self._timeout_checks: Optional[Dict[str, TimeoutCheck]] = None
        self._on_timeout_callback: Optional[Coroutine] = None

        if value_constraints is not None:
            self._value_checks: Dict[str, ValueCheck] = {
                metric: ValueCheck(**value_constraints) for metric in self._metrics
            }

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
        return self._value_checks is not None

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

    def check_values(
        self, metric: str, values: Iterable[float]
    ) -> Iterable[Tuple[Status, str]]:
        if not self._has_value_checks():
            return list()

        check: ValueCheck = self._value_checks.get(metric)
        if check is None:
            raise ValueError(f'Metric "{metric}" not known to check "{self._name}"')

        reports = list()
        for value in values:
            (status, changed) = check.get_status(value)
            if changed:
                self._status_cache.update_status(metric, value, status)
                status = self._status_cache.overall_status()
                assert status is not None

                status_message: str
                if status == Status.OK:
                    status_message = "All metrics OK"
                else:
                    critical = self._status_cache.critical
                    warning = self._status_cache.warning

                    header_line = list()
                    details = list()

                    if len(critical):
                        header_line.append(f"{len(critical)} metric(s) CRITICAL")
                        for metric, critical_value in critical.items():
                            details.append(
                                f"CRITICAL: {metric} = {critical_value:.12g}"
                            )

                    if len(warning):
                        header_line.append(f"{len(warning)} metric(s) WARNING")
                        for metric, warn_value in warning.items():
                            details.append(f"WARNING: {metric} = {warn_value:.12g}")

                    header_line = ", ".join(header_line)
                    details = "\\n".join(details)

                    status_message = f"{header_line}\\n{details}"
                reports.append((status, status_message))

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
