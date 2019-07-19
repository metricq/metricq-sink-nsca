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

from .send_nsca import NSCAReport, Status, NSCAClient

from .check import Check

import logging
from typing import Dict, Iterable, Optional

import click
import click_log

import asyncio

import metricq
from metricq import Timedelta, Timestamp

from .logging import get_logger

logger = get_logger()

click_log.basic_config(logger)
logger.setLevel("INFO")
logger.handlers[0].formatter = logging.Formatter(
    fmt="[%(asctime)s] [%(levelname)-5s] [%(name)-20s] %(message)s"
)


class ReporterSink(metricq.DurableSink):
    """Sink that dispatches Nagios/Centreon check results via send_nsca.
    """

    def __init__(self, *args, **kwargs):
        # these are configured after connecting, see _configure().
        self._reporting_host: str = None
        self._nsca_client: NSCAClient = None
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

    def _init_checks(self, check_config) -> None:
        self._clear_checks()
        for check, config in check_config.items():
            logger.info(f'Setting up new check "{check}"')
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
                c: config.get(c)
                for c in (
                    "warning_below",
                    "warning_above",
                    "critical_below",
                    "critical_above",
                )
            }

            # timout is optional too
            timeout: Optional[str] = config.get("timeout")
            self._checks[check] = Check(
                name=check,
                metrics=metrics,
                value_constraints=value_constraints,
                timeout=timeout,
                on_timeout=self._send_timeout_report,
            )

    async def connect(self):
        await super().connect()
        metrics = set.union(*(set(check.metrics()) for check in self._checks.values()))
        await self.subscribe(metrics=metrics)

    async def subscribe(self, metrics: Iterable[str], **kwargs) -> None:
        return await super().subscribe(metrics=list(metrics), **kwargs)

    @metricq.rpc_handler("config")
    async def _configure(self, checks, reporting_host, nsca_host, **_kwargs) -> None:
        logger.info(
            f"Received configuration: "
            f"sending checks from {reporting_host} to NSCA host {nsca_host}"
        )

        self._reporting_host = reporting_host

        # asynchronously spawn an NSCA client, used to deliver check results
        if self._nsca_client is not None:
            self._nsca_client.terminate()
            self._nsca_client = None
        self._nsca_client = await NSCAClient.spawn(
            nsca_host, config_file="send_nsca.cfg"
        )

        self._init_checks(checks)

    async def _on_data_chunk(self, metric: str, data_chunk):
        # check that all values in this data chunk are within the desired
        # thresholds
        await self._check_values(metric, data_chunk.value)

        # "bump" all timeout checks with the last timestamp for which we
        # received values, i.e. reset the asynchronous timers that would
        # fire if we do not receive value for too long.
        last_timestamp = Timestamp(sum(data_chunk.time_delta))
        await self._bump_timeout_checks(metric, last_timestamp)

        # flush all reports to the NSCA host
        await self._nsca_client.flush()

    async def on_data(self, _metric, _timestamp, _value):
        """Functionality implemented in _on_data_chunk
        """

    async def _check_values(self, metric: str, values: Iterable[float]) -> None:
        reports = list()
        check: Check
        for name, check in self._checks.items():
            if metric in check:
                for value in values:
                    status, changed = check.check_value(metric, value)
                    if changed:
                        report = NSCAReport(
                            f'Metric "{metric}": {value}',
                            status=status,
                            host=self._reporting_host,
                            service=name,
                        )
                        reports.append(report)

        for report in reports:
            self._nsca_client.send_report(report)

    async def _bump_timeout_checks(
        self, metric: str, last_timestamp: Timestamp
    ) -> None:
        check: Check
        await asyncio.gather(
            *tuple(
                check.bump_timeout_check(metric, last_timestamp)
                for check in self._checks.values()
                if metric in check
            )
        )

    async def _send_timeout_report(
        self,
        check_name: str,
        metric: str,
        timeout: Timedelta,
        last_timestamp: Optional[Timestamp],
    ):
        message = f'Metric "{metric}" timed out after {timeout}: '
        if last_timestamp is None:
            message += "never received any values"
        else:
            date_str = last_timestamp.datetime.astimezone()
            message += f"received last value at {date_str}"

        logger.warning(f'Check "{check_name}": {message}')

        report = NSCAReport(
            message,
            status=Status.WARNING,
            host=self._reporting_host,
            service=check_name,
        )
        self._nsca_client.send_report(report)
        await self._nsca_client.flush()


@click.command()
@click.option("--metricq-server", "-s", default="amqp://localhost/")
@click.option("--token", "-t", default="sink-nsca")
@click_log.simple_verbosity_option(logger)
def report_cmd(metricq_server, token):
    reporter = ReporterSink(management_url=metricq_server, token=token)
    reporter.run()
