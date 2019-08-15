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
from asyncio import subprocess
from enum import Enum
from typing import Optional

from .logging import get_logger

logger = get_logger()


class Status(Enum):
    OK = 0
    WARNING = 1
    CRITICAL = 2


class NSCAReport:
    def __init__(self, message, host, status=Status.OK, service=None):
        self.message = str(message)
        self.status = Status(status)
        self.service = service
        self.host = host

    def serialize(self, field_delimiter="\t") -> bytes:
        if self.service is None:
            # Host check result
            fields = (self.host, self.status.value, self.message)
        else:
            # Service check result
            fields = (self.host, self.service, self.status.value, self.message)

        return (field_delimiter.join(str(f) for f in fields) + "\n").encode("utf-8")

    def __repr__(self):
        return (
            f"NSCAReport("
            f"host={self.host!r}, "
            f"service={self.service!r}, "
            f"status={self.status!r}"
            f"message={self.message!r}, "
            f")"
        )


class NSCAClient:
    def __init__(
        self, process: subprocess.Process, field_delimiter: Optional[str] = None
    ):
        self._process = process
        self._field_delimiter = field_delimiter or "\t"

    @staticmethod
    async def spawn(
        host_addr,
        executable: str = "send_nsca",
        config_file: Optional[str] = None,
        field_delimiter: Optional[str] = None,
    ) -> "NSCAClient":
        args = list()

        def add_arg(args, switch, argument):
            if argument is not None:
                args.extend([switch, argument])

        add_arg(args, "-H", host_addr)
        add_arg(args, "-c", config_file)
        add_arg(args, "-d", field_delimiter)

        logger.info("Running NSCA client {} with arguments {}", executable, args)

        process = await asyncio.create_subprocess_exec(
            executable, *args, stdin=asyncio.subprocess.PIPE
        )

        return NSCAClient(process=process, field_delimiter=field_delimiter)

    def send_report(self, report: NSCAReport):
        logger.debug(f"Sending NSCA report: {report!r}")
        self._process.stdin.write(
            report.serialize(field_delimiter=self._field_delimiter)
        )

    async def flush(self):
        self._process.stdin.write(b"\x17")
        await self._process.stdin.drain()

    def terminate(self):
        self._process.terminate()
