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

from asyncio import FIRST_COMPLETED, Queue, Task, create_task, sleep, wait
from dataclasses import dataclass
from typing import AsyncIterator, Optional

from metricq.types import Timedelta

from .state import State


@dataclass
class Report:
    service: str
    state: State
    message: str


class ReportQueue:
    def __init__(self):
        self._queue: Queue[Report] = Queue()

    def put(self, report: Report) -> None:
        self._queue.put_nowait(report)

    async def batch(self, timeout: Timedelta) -> AsyncIterator[Report]:
        timeout_task = create_task(sleep(timeout.s))

        report_task: Optional[Task] = None
        while True:
            if report_task is None:
                report_task = create_task(self._queue.get())

            done, pending = await wait(
                (report_task, timeout_task),
                timeout=None,
                return_when=FIRST_COMPLETED,
            )

            if report_task in done:
                yield report_task.result()
                report_task = None

            if timeout_task in done:
                if report_task is not None:
                    report_task.cancel()
                return
