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

import metricq
from metricq import Timestamp, Timedelta
import aionsca

from .check import Check, TvPair, CheckReport
from .logging import get_logger

logger = get_logger(__name__)


class ReporterSink(metricq.DurableSink):
    """Sink that dispatches Nagios/Centreon check results via send_nsca.
    """

    def __init__(self, *args, **kwargs):
        # these are configured after connecting, see _configure().
        self._reporting_host: str = None
        self._nsca_client_args: Optional[Dict] = None
        self._checks: Dict[str, Check] = dict()
        self._check_configs: Dict[str] = dict()
        self._global_resend_interval: Optional[Timedelta] = None

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
            raise ValueError(f"Check does not contain any metrics")

        if not (
            isinstance(metrics, list)
            and len(metrics) > 0
            and all(isinstance(m, str) for m in metrics)
        ):
            raise ValueError(
                f'Configured key "metrics" must be a nonempty list of metric names'
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

        logger.info(
            f'Setting up check "{name}" with '
            f"value_contraints={value_constraints!r}, "
            f"timeout={timeout!r}, "
            f"plugins={list(plugins.keys())},"
            f"resend_interval={resend_interval} and "
            f"transition_debounce_window={transition_debounce_window} "
        )
        return Check(
            name=name,
            metrics=metrics,
            value_constraints=value_constraints,
            resend_interval=resend_interval,
            timeout=timeout,
            on_timeout=self._on_check_timeout,
            plugins=plugins,
            transition_debounce_window=transition_debounce_window,
        )

    def _add_check(self, name: str, config: dict):
        if not self._checks:
            self._checks = dict()
        logger.debug('Adding check "{}"', name)
        self._checks[name] = self._parse_check_from_config(name, config)
        self._check_configs[name] = config

    def _remove_check(self, name: str):
        if self._checks:
            self._check_configs.pop(name)
            check: Check = self._checks.pop(name)
            if check is not None:
                logger.debug('Removing check "{}"', name)
                check.cancel_timeout_checks()

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
            logger.debug("Removing check {}", name)
            self._remove_check(name)

        for name in to_add:
            logger.debug("Adding new check {}", name)
            self._add_check(name, updated_check_config[name])

        for name in to_update:
            old_config = self._check_configs[name]
            updated_config = updated_check_config[name]
            if updated_config != old_config:
                logger.debug("Updating check {}", name)
                self._remove_check(name)
                self._add_check(name, updated_config)
            else:
                logger.debug("Skipping update of unchanged check {}", name)

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
        logger.info(f"Successfully subscribed to all required metrics")

    async def subscribe(self, metrics: Iterable[str], **kwargs) -> None:
        return await super().subscribe(metrics=list(metrics), **kwargs)

    @metricq.rpc_handler("config")
    async def _configure(
        self,
        *,
        checks,
        nsca: dict,
        reporting_host: str = gethostname(),
        resend_interval: str = "3min",
        **_kwargs,
    ) -> None:
        self._reporting_host = reporting_host
        try:
            self._global_resend_interval = Timedelta.from_string(resend_interval)
        except ValueError as e:
            logger.error(
                f'Invalid resend interval "{resend_interval}" in configuration: {e}'
            )
            raise

        await self._init_nsca_client(**nsca)

        if not self._checks:
            self._init_checks(checks)
        else:
            self._update_checks(checks)

        logger.info(
            f"Configured NSCA reporter sink for host {self._reporting_host} and checks {', '.join(self._checks)!r}"
        )

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
                    dict(
                        host=self._reporting_host,
                        service=name,
                        state=report.state,
                        message=report.message,
                    )
                )

        await self._send_reports(*reports)

    async def _send_reports(self, *reports):
        if not reports:
            logger.debug("Not sending empty report batch")
            return

        try:
            logger.debug(f"Sending {len(reports)} report(s)")
            async with aionsca.Client(**self._nsca_client_args) as client:
                for report in reports:
                    await client.send_report(**report)
        except (ConnectionError, OSError) as e:
            # The OSError is likely a collection of connection errors,
            # see https://bugs.python.org/issue29980.
            host, port = (
                self._nsca_client_args.get("host", ""),
                self._nsca_client_args.get("port", ""),
            )
            host_spec = "" if not host and not port else f"at {host}:{port}"
            logger.error(f"Failed to send reports to NSCA server {host_spec}: {e}")

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
