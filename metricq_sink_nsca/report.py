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

from .send_nsca import NSCAReport, Status, SendNSCA

# from .checks import Check
from .check import Check, ValueCheck
from .timeout_check import TimeoutCheck

import json
import logging
from typing import Dict, Iterable, Optional

import click
import click_log

import asyncio
from asyncio import subprocess, create_subprocess_exec

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
    def __init__(self, *args, **kwargs):
        self._reporting_host: str = None
        self._send_nsca_proc: SendNSCA = None
        self._checks: Dict[str, Check] = None
        # self._timeout_checks: Dict[str, Dict[str, TimeoutCheck]] = None

        super().__init__(*args, **kwargs)

    def _init_checks(self, check_config) -> None:
        self._checks = dict()
        for check, config in check_config.items():
            metrics = config.get("metrics")
            if metrics is None:
                raise ValueError(f"Check '{check}' does not contain any metrics")

            value_constraints = {
                c: config.get(c)
                for c in (
                    "warning_below",
                    "warning_above",
                    "critical_below",
                    "critical_above",
                )
            }

            timeout: Optional[str] = config.get("timeout")
            self._checks[check] = Check(
                name=check,
                metrics=metrics,
                value_constraints=value_constraints,
                timeout=timeout,
                on_timeout=self._send_timeout_report,
            )

        logger.info(click.style("Running checks:", fg="blue"))
        for name, check in self._checks.items():
            logger.info(click.style(f"* {name}", fg="blue"))

    async def connect(self):
        await super().connect()
        metrics = set.union(*(set(check.metrics()) for check in self._checks.values()))
        await self.subscribe(metrics=metrics)

    async def subscribe(self, metrics: Iterable[str], **kwargs) -> None:
        return await super().subscribe(metrics=list(metrics), **kwargs)

    @metricq.rpc_handler("config")
    async def config(self, checks, reporting_host, nsca_host, **kwargs) -> None:
        logger.info(f"Sending checks from {reporting_host} to {nsca_host}")

        self._reporting_host = reporting_host
        self._send_nsca_proc: SendNSCA = None

        self._send_nsca_proc = await SendNSCA.spawn(
            nsca_host, config_file="send_nsca.cfg"
        )

        self._init_checks(checks)

    async def _on_data_chunk(self, metric: str, data_chunk):
        last_timestamp = Timestamp(sum(data_chunk.time_delta))
        last_value = data_chunk.value[-1]
        await self.on_data(metric, last_timestamp, last_value)

    async def on_data(self, metric, timestamp, value):
        # await asyncio.sleep(1)
        check: Check
        for name, check in self._checks.items():
            if metric in check:
                await check.update_timeout_check(metric, timestamp)
                status, changed = check.check_value(metric, value)
                if changed:
                    report = NSCAReport(
                        f'Metric "{metric}": {value}',
                        status=status,
                        host=self._reporting_host,
                        service=name,
                    )
                    self._send_nsca_proc.send_report(report)

        await self._send_nsca_proc.flush()

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
        self._send_nsca_proc.send_report(report)
        await self._send_nsca_proc.flush()


def get_host_addr():
    import socket

    return socket.gethostbyname(socket.gethostname())


@click.command()
@click.option("--metricq-server", "-s", default="amqp://localhost/")
@click.option("--token", "-t", default="sink-nsca")
@click_log.simple_verbosity_option(logger)
def report_cmd(metricq_server, token):
    reporter = ReporterSink(management_url=metricq_server, token=token)
    reporter.run()
