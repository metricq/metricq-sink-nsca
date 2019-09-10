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
from typing import Dict, Iterable, Optional, List
from socket import gethostname
from itertools import accumulate
from dataclasses import dataclass

import metricq
from metricq import Timestamp

from .check import Check
from .logging import get_logger
from .state import State

from .check import Check, TvPair, CheckReport
from .logging import get_logger

logger = get_logger(__name__)


@dataclass
class NscaConfig:
    host: str = "localhost"
    port: int = 5667
    config_file: str = "/etc/nsca/send_nsca.cfg"
    executable: str = "/usr/sbin/send_nsca"


@dataclass
class NscaReport:
    host: str
    service: str
    state: State
    message: str


class ReporterSink(metricq.DurableSink):
    """Sink that dispatches Nagios/Centreon check results via send_nsca.
    """

    def __init__(self, *args, **kwargs):
        # these are configured after connecting, see _configure().
        self._reporting_host: str = None
        self._nsca_config: Optional[NscaConfig] = None
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
        self._nsca_config = NscaConfig(**nsca)

        self._init_checks(checks)
        logger.info(
            f"Configured NSCA reporter sink for host {self._reporting_host} and checks {', '.join(self._checks)!r}"
        )
        logger.debug(f"NSCA config: {self._nsca_config!r}")

        # send initial reports
        reports = list()
        for name, check in self._checks.items():
            logger.debug(f"Sending initial report for check {name!r}")
            state, message = check.format_overall_state()
            reports.append(
                NscaReport(
                    host=self._reporting_host,
                    service=name,
                    state=state,
                    message=message,
                )
            )

        await self._send_reports(*reports)

    async def _on_data_chunk(self, metric: str, data_chunk):
        tv_pairs = [
            TvPair(timestamp=Timestamp(t), value=v)
            for t, v in zip(accumulate(data_chunk.time_delta), data_chunk.value)
        ]

        # check that all values in this data chunk are within the desired
        # thresholds
        await self._check_values(metric, tv_pairs)

        # "bump" all timeout checks with the last timestamp for which we
        # received values, i.e. reset the asynchronous timers that would
        # fire if we do not receive value for too long.
        last_timestamp = tv_pairs[-1].timestamp
        await self._bump_timeout_checks(metric, last_timestamp)

    async def on_data(self, _metric, _timestamp, _value):
        """Functionality implemented in _on_data_chunk
        """

    async def _check_values(self, metric: str, tv_pairs: List[TvPair]) -> None:
        reports = list()
        check: Check
        for name, check in self._checks.items():
            report: CheckReport
            for report in check.generate_reports(metric, tv_pairs):
                reports.append(
                    NscaReport(
                        host=self._reporting_host,
                        service=name,
                        state=report.state,
                        message=report.message,
                    )
                )

        await self._send_reports(*reports)

    async def _send_reports(self, *reports: NscaReport):
        if not reports:
            return

        report: NscaReport
        report_blocks = list()
        for report in reports:
            message = report.message.replace("\n", "\\n").encode("ascii")
            max_len = 4096
            if len(message) >= max_len:
                SNIP = br"\n...\nSOME METRICS OMITTED"
                cut = message.rfind(b"\\n", 0, max_len - len(SNIP))
                message = message[:cut] + SNIP
            assert len(message) <= max_len
            block = b";".join(
                (
                    report.host.encode("ascii"),
                    report.service.encode("ascii"),
                    str(report.state.value).encode("ascii"),
                    message,
                )
            )
            report_blocks.append(block)
        nsca: NscaConfig = self._nsca_config
        proc = await asyncio.create_subprocess_exec(
            nsca.executable,
            "-H",
            nsca.host,
            "-p",
            str(nsca.port),
            "-c",
            nsca.config_file,
            "-d",
            ";",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
        )

        stdout_data: bytes
        stdout_data, _stderr_data = await proc.communicate(
            input=b"\x17".join(report_blocks)
        )
        rc = proc.returncode
        assert rc is not None

        def log_output(log_level_function, msg_bytes):
            try:
                msg = msg_bytes.decode("ascii")
                for line in msg.splitlines():
                    log_level_function("send_nsca: " + line)
            except UnicodeError:
                log_level_function("send_nsca: failed to decode output")

        if rc != 0:
            logger.error(
                f"Failed to send reports to NSCA host ({nsca.host}:{nsca.port}): "
                f"returncode={rc}"
            )
            log_output(logger.error, stdout_data)
        else:
            log_output(logger.debug, stdout_data)

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

    async def _on_check_timeout(self, check_name: str, state: State, message: str):
        logger.warning(f"Check {check_name!r} is {state.name}: {message}")
        await self._send_reports(
            NscaReport(
                host=self._reporting_host,
                service=check_name,
                state=state,
                message=message,
            )
        )
