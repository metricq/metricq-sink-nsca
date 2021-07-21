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

import asyncio
from itertools import accumulate
from math import isnan
from socket import gethostname
from typing import Dict, Iterable, List, Optional

import metricq
from metricq import Timedelta, Timestamp

from metricq_sink_nsca.config_parser import parse_timedelta

from .check import Check, CheckConfig, TvPair
from .logging import get_logger
from .nsca import Nsca, NscaConfig, NscaReport
from .override import Overrides, OverridesConfig
from .report_queue import Report, ReportQueue
from .subtask import subtask
from .version import version as client_version

logger = get_logger(__name__)

DEFAULT_HOSTNAME = gethostname()
DEFAULT_RESEND_INTERVAL = Timedelta.from_s(3 * 60)


class ReporterSink(metricq.DurableSink):
    """Sink that dispatches Nagios/Centreon check results via send_nsca."""

    def __init__(self, dry_run: bool = False, *args, **kwargs):
        self._dry_run: bool = dry_run

        # these are configured after connecting, see _configure().
        self._nsca: Optional[Nsca] = None
        self._reporting_host: Optional[str] = None
        self._resend_interval: Timedelta = DEFAULT_RESEND_INTERVAL
        self._overrides: Overrides = Overrides.empty()
        self._checks: Dict[str, Check] = dict()
        self._has_value_checks: bool = False
        self._report_queue = ReportQueue()

        super().__init__(*args, client_version=client_version, **kwargs)

    @property
    def nsca(self) -> Nsca:
        assert (
            self._nsca is not None
        ), "ReporterSink.nsca was accessed before sink was configured"
        return self._nsca

    @property
    def reporting_host(self) -> str:
        assert (
            self._reporting_host is not None
        ), "ReporterSink.reporting_host was accessed before sink was configured"
        return self._reporting_host

    # TODO: remove
    def _clear_checks(self):
        if not self._checks:
            return

        logger.info("Cancelling running checks...")
        check: Check
        for name, check in self._checks.items():
            logger.info(f'Cancelling check "{name}"')
            check.cancel()

        self._checks = dict()

    def _add_check(self, name: str, config: CheckConfig):
        if not self._checks:
            self._checks = dict()
        logger.info('Adding check "{}"', name)

        check = Check.from_config(
            name,
            config=config,
            report_queue=self._report_queue,
            resend_interval=self._resend_interval,
            overrides=self._overrides,
        )

        check.start()
        self._checks[name] = check

    async def _remove_check(self, name: str, timeout: Optional[float]):
        logger.info('Removing check "{}"', name)
        if self._checks:
            check: Optional[Check] = self._checks.pop(name, None)
            if check is not None:
                try:
                    await asyncio.wait_for(check.stop(), timeout=timeout)
                except asyncio.TimeoutError:
                    logger.exception('Failed to remove check "{}"', name)
                    raise
            else:
                logger.warn('Check "{}" did not exist', name)

    def _init_checks(self, check_config: Dict[str, CheckConfig]) -> None:
        self._checks = dict()
        for name, config in check_config.items():
            self._add_check(name, config)

    async def _update_checks(self, updated_config: Dict[str, CheckConfig]) -> None:
        new = set(updated_config.keys())
        old = set(self._checks.keys())

        to_remove = old - new
        to_add = new - old
        to_update_candidate = new & old

        await asyncio.gather(
            *(self._remove_check(name, timeout=1.0) for name in to_remove)
        )

        for name in to_add:
            self._add_check(name, updated_config[name])

        to_update = dict()
        for name in to_update_candidate:
            old_config = self._checks[name].config
            new_config = updated_config[name]
            if new_config != old_config:
                to_update[name] = new_config
            else:
                logger.info("Skipping update of unchanged check {}", name)

        async def remove_and_add(name: str, new_config: CheckConfig):
            logger.info('Removing out-of-date check "{}"...', name)
            await self._remove_check(name, timeout=1.0)
            logger.info('Adding check "{}" with updated configuration', name)
            self._add_check(name, new_config)

        await asyncio.gather(
            *(remove_and_add(name, config) for name, config in to_update.items())
        )

    async def connect(self):
        await super().connect()
        logger.info("Successfully connected to the MetricQ network")
        metrics = set().union(
            *(
                set(check.metrics()) | set(check.extra_metrics())
                for check in self._checks.values()
            )
        )
        logger.info(f"Subscribing to {len(metrics)} metric(s)...")
        await self.subscribe(metrics=metrics)
        logger.info("Successfully subscribed to all required metrics")

        self._send_reports_loop.start()

    async def subscribe(self, metrics: Iterable[str], **kwargs) -> None:
        return await super().subscribe(metrics=list(metrics), **kwargs)

    @metricq.rpc_handler("config")
    async def _configure(
        self,
        *,
        nsca: NscaConfig,
        checks: Dict[str, CheckConfig],
        reporting_host: Optional[str] = None,
        resend_interval: Optional[str] = None,
        overrides: Optional[OverridesConfig] = None,
        **_config,
    ) -> None:
        self._nsca = Nsca.from_config(nsca)
        self._reporting_host = (
            reporting_host if reporting_host is not None else DEFAULT_HOSTNAME
        )
        self._resend_interval = parse_timedelta(
            resend_interval, default=DEFAULT_RESEND_INTERVAL
        )
        self._overrides = Overrides.from_config(overrides)

        if not self._checks:
            self._init_checks(checks)
        else:
            await self._update_checks(checks)

        self._has_value_checks = any(
            c._has_value_checks() for c in self._checks.values()
        )

        logger.info(
            f"Configured NSCA reporter sink for host {self.reporting_host} and checks {', '.join(self._checks)!r}"
        )
        logger.debug(f"NSCA config: {self.nsca!r}")

    async def _on_data_chunk(self, metric: str, data_chunk):
        # Fast-path if there are no value checks: do not decode the whole data
        # chunk, only extract the last timestamp and bump timeout checks.
        if not self._has_value_checks:
            if len(data_chunk.time_delta) > 0:
                last_timestamp = Timestamp(sum(data_chunk.time_delta))
                self._bump_timeout_checks(metric, last_timestamp)
            return

        tv_pairs = [
            TvPair(timestamp=Timestamp(t), value=v)
            for t, v in zip(accumulate(data_chunk.time_delta), data_chunk.value)
            if not isnan(v)
        ]

        if len(tv_pairs) == 0:
            logger.debug(f"No non-NaN values in DataChunk for metric {metric!r}")
            return

        # check that all values in this data chunk are within the desired
        # thresholds
        for check in self._checks.values():
            check.check(metric, tv_pairs)

        # "bump" all timeout checks with the last timestamp for which we
        # received values, i.e. reset the asynchronous timers that would
        # fire if we do not receive value for too long.
        last_timestamp = tv_pairs[-1].timestamp
        self._bump_timeout_checks(metric, last_timestamp)

    async def on_data(self, _metric, _timestamp, _value):
        """Functionality implemented in _on_data_chunk"""

    async def _send_reports(self, reports: List[NscaReport]):
        if not reports:
            return

        logger.debug("Sending {} report(s)", len(reports))

        if self._dry_run:
            return

        await self.nsca.send(reports)

    def _bump_timeout_checks(self, metric: str, last_timestamp: Timestamp) -> None:
        check: Check
        for check in self._checks.values():
            if metric in check:
                check.bump_timeout_check(metric, last_timestamp)

    @subtask
    async def _send_reports_loop(self) -> None:
        while True:
            report: Report
            reports = [
                NscaReport(
                    host=self.reporting_host,
                    service=report.service,
                    state=report.state,
                    message=report.message,
                )
                async for report in self._report_queue.batch(
                    timeout=Timedelta.from_s(5.0)
                )
            ]
            await self._send_reports(reports)
