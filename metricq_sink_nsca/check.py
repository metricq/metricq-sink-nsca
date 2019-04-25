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

from typing import Iterable, Dict, Optional, Coroutine, Set

from metricq.types import Timedelta, Timestamp

from .value_check import ValueCheck, AbnormalRange
from .timeout_check import TimeoutCheck
from .send_nsca import Status


class Check:
    def __init__(
        self,
        name: str,
        metrics: Iterable[str],
        value_constraints: Dict[str, float],
        timeout: Optional[str] = None,
        on_timeout: Optional[Coroutine] = None,
    ):
        self._name = name
        self._metrics: Set[str] = set(metrics)

        self._value_checks: Dict[str, ValueCheck] = {
            metric: ValueCheck(**value_constraints) for metric in self._metrics
        }

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

    def _get_on_timeout_callback(self, metric) -> Coroutine:
        async def on_timeout(timeout, last_timestamp):
            await self._on_timeout_callback(
                check_name=self._name,
                metric=metric,
                timeout=timeout,
                last_timestamp=last_timestamp,
            )

        return on_timeout

    def check_value(self, metric: str, value: float) -> (Status, bool):
        try:
            return self._value_checks[metric].get_status(value)
        except KeyError:
            raise ValueError(f'Metric "{metric}" not known to check')

    async def update_timeout_check(self, metric: str, timestamp: Timestamp) -> None:
        try:
            self._timeout_checks[metric].bump(timestamp)
        except KeyError:
            raise ValueError(f'Metric "{metric}" not known to check')

    def metrics(self) -> Iterable[str]:
        return self._metrics

    def __contains__(self, metric: str) -> bool:
        return metric in self._metrics
