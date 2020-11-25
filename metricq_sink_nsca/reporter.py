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
from dataclasses import dataclass
from dataclasses import fields as dataclass_fields
from itertools import accumulate
from math import isnan
from socket import gethostname
from typing import Dict, Iterable, Optional

import metricq
from metricq import Timedelta, Timestamp

from .check import Check, TvPair
from .logging import get_logger
from .report_queue import Report, ReportQueue
from .state import State
from .subtask import subtask
from .version import version as client_version

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


DEFAULT_HOSTNAME = gethostname()


class ReporterSink(metricq.DurableSink):
    """Sink that dispatches Nagios/Centreon check results via send_nsca."""

    def __init__(self, dry_run: bool = False, *args, **kwargs):
        self._dry_run: bool = dry_run

        # these are configured after connecting, see _configure().
        self._reporting_host: str = None
        self._nsca_config: Optional[NscaConfig] = None
        self._checks: Dict[str, Check] = dict()
        self._check_configs: Dict[str] = dict()
        self._has_value_checks: bool = False
        self._global_resend_interval: Optional[Timedelta] = None
        self._report_queue = ReportQueue()

        super().__init__(*args, client_version=client_version, **kwargs)

    def _clear_checks(self):
        if not self._checks:
            return

        logger.info("Cancelling running checks...")
        check: Check
        for name, check in self._checks.items():
            logger.info(f'Cancelling check "{name}"')
            check.cancel()

        self._checks = dict()

    def _parse_check_from_config(self, name: str, config: dict) -> Check:
        def config_get(cfg_key: str, convert_with=None, default=None) -> Optional:
            value = config.get(cfg_key)
            if value is None:
                return default
            else:
                try:
                    return value if convert_with is None else convert_with(value)
                except ValueError as e:
                    raise ValueError(
                        f'Invalid config key "{cfg_key}"={value}: {e}'
                    ) from e

        metrics = config.get("metrics")
        if metrics is None:
            raise ValueError("Check does not contain any metrics")

        if not (
            isinstance(metrics, list)
            and len(metrics) > 0
            and all(isinstance(m, str) for m in metrics)
        ):
            raise ValueError(
                'Configured key "metrics" must be a nonempty list of metric names'
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

        # the following are all optional configuration items
        timeout: Optional[Timedelta] = config_get(
            "timeout", convert_with=Timedelta.from_string, default=None
        )
        resend_interval: Timedelta = config_get(
            "resend_interval",
            convert_with=Timedelta.from_string,
            default=self._global_resend_interval,
        )
        plugins: dict = config_get("plugins", default={})
        transition_debounce_window = config_get(
            "transition_debounce_window",
            convert_with=Timedelta.from_string,
            default=None,
        )
        transition_postprocessing = config_get(
            "transition_postprocessing", default=None
        )

        logger.info(
            f'Setting up check "{name}" with '
            f"value_contraints={value_constraints!r}, "
            f"timeout={timeout}, "
            f"plugins={list(plugins.keys())}, "
            f"resend_interval={resend_interval}, "
            f"transition_debounce_window={transition_debounce_window} and "
            f"transition_postprocessing={transition_postprocessing}"
        )
        return Check(
            name=name,
            metrics=metrics,
            report_queue=self._report_queue,
            value_constraints=value_constraints,
            resend_interval=resend_interval,
            timeout=timeout,
            plugins=plugins,
            transition_debounce_window=transition_debounce_window,
            transition_postprocessing=transition_postprocessing,
        )

    def _add_check(self, name: str, config: dict):
        if not self._checks:
            self._checks = dict()
        logger.info('Adding check "{}"', name)
        check = self._parse_check_from_config(name, config)
        check.start()
        self._checks[name] = check
        self._check_configs[name] = config

    def _remove_check(self, name: str):
        logger.info('Removing check "{}"', name)
        if self._checks:
            self._check_configs.pop(name)
            check: Check = self._checks.pop(name, None)
            if check is not None:
                check.cancel()
            else:
                logger.warn('Check "{}" did not exist', name)

    def _init_checks(self, check_config) -> None:
        self._checks = dict()
        for name, config in check_config.items():
            self._add_check(name, config)

    def _update_checks(self, updated_check_config) -> None:
        new = set(updated_check_config.keys())
        old = set(self._checks.keys())

        to_remove = old - new
        to_add = new - old
        to_update = new & old

        for name in to_remove:
            self._remove_check(name)

        for name in to_add:
            self._add_check(name, updated_check_config[name])

        for name in to_update:
            old_config = self._check_configs[name]
            updated_config = updated_check_config[name]
            if updated_config != old_config:
                logger.info("Updating check {}", name)
                self._remove_check(name)
                self._add_check(name, updated_config)
            else:
                logger.info("Skipping update of unchanged check {}", name)

    async def connect(self):
        await super().connect()
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
        checks,
        nsca: dict,
        reporting_host: str = DEFAULT_HOSTNAME,
        resend_interval: str = "3min",
        **_kwargs,
    ) -> None:
        self._reporting_host = reporting_host
        self._nsca_config = NscaConfig(
            **{
                cfg_key: v
                for cfg_key, v in nsca.items()
                # ignore unknown keys in NSCA config
                if cfg_key in set(f.name for f in dataclass_fields(NscaConfig))
            }
        )

        try:
            self._global_resend_interval = Timedelta.from_string(resend_interval)
        except ValueError as e:
            logger.error(
                f'Invalid resend interval "{resend_interval}" in configuration: {e}'
            )
            raise

        if not self._checks:
            self._init_checks(checks)
        else:
            self._update_checks(checks)

        c: Check
        self._has_value_checks = any(
            c._has_value_checks() for c in self._checks.values()
        )

        logger.info(
            f"Configured NSCA reporter sink for host {self._reporting_host} and checks {', '.join(self._checks)!r}"
        )
        logger.debug(f"NSCA config: {self._nsca_config!r}")

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

    async def _send_reports(self, *reports: NscaReport):
        if not reports:
            return

        logger.debug(f"Sending {len(reports)} report(s)")

        if self._dry_run:
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
                f"Failed to send reports to NSCA host at {nsca.host}:{nsca.port}: "
                f"returncode={rc}"
            )
            log_output(logger.error, stdout_data)
        else:
            log_output(logger.debug, stdout_data)

    def _bump_timeout_checks(self, metric: str, last_timestamp: Timestamp) -> None:
        check: Check
        for check in self._checks.values():
            if metric in check:
                check.bump_timeout_check(metric, last_timestamp)

    @subtask
    async def _send_reports_loop(self):
        while True:
            report: Report
            reports = [
                NscaReport(
                    host=self._reporting_host,
                    service=report.service,
                    state=report.state,
                    message=report.message,
                )
                async for report in self._report_queue.batch(
                    timeout=Timedelta.from_s(5)
                )
            ]
            await self._send_reports(*reports)
