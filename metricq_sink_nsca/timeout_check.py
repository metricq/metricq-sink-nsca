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
from asyncio import CancelledError, Event
from typing import Optional, Protocol

from metricq.types import Timedelta, Timestamp

from .logging import get_logger
from .subtask import subtask

logger = get_logger(__name__)


class TimeoutCallback(Protocol):
    def __call__(
        self, *, timeout: Timedelta, last_timestamp: Optional[Timestamp]
    ) -> None:
        ...


class TimeoutCheck:
    def __init__(
        self,
        timeout: Timedelta,
        on_timeout: TimeoutCallback,
        grace_period: Optional[Timedelta] = None,
        name: Optional[str] = None,
    ):
        self._timeout = timeout
        self._timeout_callback: TimeoutCallback = on_timeout
        self._grace_period = Timedelta(0) if grace_period is None else grace_period
        self._name = name

        self._last_timestamp: Optional[Timestamp] = None
        self._new_timestamp_event: Event = Event()
        self._throttle = False

    def start(self):
        self._run.start()

    def cancel(self):
        self._run.cancel()

    def bump(self, last_timestamp: Timestamp):
        self._last_timestamp = last_timestamp
        self._throttle = False
        self._new_timestamp_event.set()

    def _run_timeout_callback(self):
        self._timeout_callback(
            timeout=self._timeout, last_timestamp=self._last_timestamp
        )

    @subtask
    async def _run(self):
        logger.info("{!r}: started", self)
        try:
            while True:
                if self._last_timestamp is None or self._throttle:
                    # We either never got bumped or we just missed a deadline
                    # and ran the timeout callback.  Wait for the entire
                    # timeout duration in either case, so that we don't spam
                    # the timeout callback.
                    timeout = self._timeout + self._grace_period
                    await self._run_timeout_callback_after(timeout)
                else:
                    # Calculate a deadline by which we expect the next bump,
                    # based on the last time at which we got bumped.
                    # We assume our local clock and the clock source for the
                    # last timestamp to be synchronized within the grace period.
                    # If the deadline is in the past, immediately run the
                    # timeout callback.
                    now = Timestamp.now()
                    deadline = self._last_timestamp + self._timeout + self._grace_period
                    if deadline <= now:
                        logger.debug("{!r}: deadline in the past!", self)
                        self._run_timeout_callback()
                        self._throttle = True
                    else:
                        wait_duration = deadline - now
                        await self._run_timeout_callback_after(wait_duration)
        except CancelledError:
            logger.info("{!r}: stopped", self)
        except Exception as e:  # pylint: disable=broad-except
            logger.exception(
                "{!r}: unexpected error inside TimeoutCheck callback: {}", self, e
            )

    async def _run_timeout_callback_after(self, timeout: Timedelta):
        try:
            logger.debug("{!r}: waiting for {}...", self, timeout)
            await asyncio.wait_for(self._new_timestamp_event.wait(), timeout=timeout.s)
            self._new_timestamp_event.clear()
        except asyncio.TimeoutError:
            logger.debug("{!r} fired!", self)
            self._run_timeout_callback()

    def __repr__(self):
        return f"<TimeoutCheck: name={self._name!r} at {id(self):#x}>"
