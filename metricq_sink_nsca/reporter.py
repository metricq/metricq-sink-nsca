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

from .check import Check
from .logging import get_logger

import asyncio
from typing import Dict, Iterable, Optional
from socket import gethostname
from itertools import accumulate

import metricq
from metricq import Timestamp
import aionsca

logger = get_logger(__name__)


class ReporterSink(metricq.DurableSink):
    """Sink that dispatches Nagios/Centreon check results via send_nsca.
    """

    def __init__(self, *args, **kwargs):
        # these are configured after connecting, see _configure().
        self._reporting_host: str = None
        self._nsca_client_args: Optional[Dict] = None
        self._checks: Dict[str, Check] = dict()

        super().__init__(*args, **kwargs)

    def _clear_checks(self):
        if not self._checks:
            return

        logger.info(f"Cancelling running checks...")
        check: Check
        for name, check in self._checks.items():
            logger.info(f'Cancelling check "{name}"')
            check.cancel_timeout_checks()

        self._checks = dict()

    async def _init_nsca_client(self, **client_args) -> None:
        """Initialize NSCA client and connect to NSCA host.

        Acceptable keyword arguments (`client_args`) are `host`, `port`,
        `encryption_method` and `password`.
        """
        self._nsca_client_args = {
            arg: client_args[arg]
            for arg in client_args
            if arg in ("host", "port", "encryption_method", "password")
        }

    def _init_checks(self, check_config) -> None:
        self._clear_checks()
        for check, config in check_config.items():
            metrics = config.get("metrics")
            if metrics is None:
                raise ValueError(f'Check "{check}" does not contain any metrics')

            if not (
                isinstance(metrics, list)
                and len(metrics) > 0
                and all(isinstance(m, str) for m in metrics)
            ):
                raise ValueError(
                    f'Check "{check}": "metrics" must be a nonempty list of metric names'
                )

            # extract ranges for warnable and critical values from the config,
            # each key is optional
            value_constraints = {
                c: config[c]
                for c in (
                    "warning_below",
                    "warning_above",
                    "critical_below",
                    "critical_above",
                    "ignore",
                )
                if c in config
            }

            # timout is optional too
            timeout: Optional[str] = config.get("timeout")
            plugins: dict = config.get("plugins", {})

            logger.info(
                f"Setting up check {check} with "
                f"value_contraints={value_constraints!r} and timeout={timeout!r}, "
                f"plugins={list(plugins.keys())}"
            )
            self._checks[check] = Check(
                name=check,
                metrics=metrics,
                value_constraints=value_constraints,
                timeout=timeout,
                on_timeout=self._on_check_timeout,
                plugins=plugins,
            )

    async def connect(self):
        await super().connect()
        metrics = set().union(
            *(
                set(check.metrics()) | set(check.extra_metrics())
                for check in self._checks.values()
            )
        )
        logger.info(f"Subscribing to {len(metrics)} metric(s): {sorted(metrics)}...")
        await self.subscribe(metrics=metrics)
        logger.info(f"Successfully subscribed to all required metrics")

    async def subscribe(self, metrics: Iterable[str], **kwargs) -> None:
        return await super().subscribe(metrics=list(metrics), **kwargs)

    @metricq.rpc_handler("config")
    async def _configure(
        self, checks, nsca: dict, reporting_host: str = gethostname(), **_kwargs
    ) -> None:
        self._reporting_host = reporting_host

        await self._init_nsca_client(**nsca)
        self._init_checks(checks)
        logger.info(
            f"Configured NSCA reporter sink for host {self._reporting_host} and checks {', '.join(self._checks)!r}"
        )

        # send initial reports
        reports = list()
        for name, check in self._checks.items():
            logger.debug(f"Sending initial report for check {name!r}")
            state, message = check.format_overall_state()
            reports.append(
                dict(
                    host=self._reporting_host,
                    service=name,
                    state=state,
                    message=message,
                )
            )

        await self._send_reports(*reports)

    async def _on_data_chunk(self, metric: str, data_chunk):
        # check that all values in this data chunk are within the desired
        # thresholds
        timestamps = list(map(Timestamp, accumulate(data_chunk.time_delta)))
        await self._check_values(metric, zip(timestamps, data_chunk.value))

        # "bump" all timeout checks with the last timestamp for which we
        # received values, i.e. reset the asynchronous timers that would
        # fire if we do not receive value for too long.
        last_timestamp = timestamps[-1]
        await self._bump_timeout_checks(metric, last_timestamp)

    async def on_data(self, _metric, _timestamp, _value):
        """Functionality implemented in _on_data_chunk
        """

    async def _check_values(self, metric: str, values: Iterable[float]) -> None:
        reports = list()
        check: Check
        for name, check in self._checks.items():
            if metric in check:
                for (state, message) in check.check_values(metric, values):
                    reports.append(
                        dict(
                            host=self._reporting_host,
                            service=name,
                            state=state,
                            message=message,
                        )
                    )

        await self._send_reports(*reports)

    async def _send_reports(self, *reports):
        if not reports:
            logger.debug("Not sending empty report batch")
            return

        try:
            async with aionsca.Client(**self._nsca_client_args) as client:
                for report in reports:
                    await client.send_report(**report)
        except (ConnectionError, OSError) as e:
            # The OSError is likely a collection of connection errors,
            # see https://bugs.python.org/issue29980.
            host, port = (
                self._nsca_client_args.get("host", "localhost"),
                self._nsca_client_args.get("port", 5667),
            )
            logger.error(f"Failed to send reports to NSCA host ({host}:{port}): {e}")

    async def _bump_timeout_checks(
        self, metric: str, last_timestamp: Timestamp
    ) -> None:
        await asyncio.gather(
            *tuple(
                check.bump_timeout_check(metric, last_timestamp)
                for check in self._checks.values()
                if metric in check
            )
        )

    async def _on_check_timeout(
        self, check_name: str, state: aionsca.State, message: str
    ):
        logger.warning(f"Check {check_name!r} is {state.name}: {message}")
        await self._send_reports(
            dict(
                host=self._reporting_host,
                service=check_name,
                state=state,
                message=message,
            )
        )
