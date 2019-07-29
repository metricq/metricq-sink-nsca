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

import os
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
    def __init__(
        self, message, status=Status.OK, host=None, service=None, field_delimiter="\t"
    ):
        self.message = str(message)
        self.status = Status(status)
        self.service = service
        self.host = host if host is not None else os.uname().nodename
        self.delimiter = field_delimiter

    def __str__(self):
        if self.service is None:
            # Host check result
            fields = (self.host, self.status.value, self.message)
        else:
            # Service check result
            fields = (self.host, self.service, self.status.value, self.message)

        return self.delimiter.join(str(f) for f in fields) + "\n"

    def __repr__(self):
        return f"NSCAReport(message={self.message!r}, status={self.status!r})"


class NSCAClient:
    def __init__(self, process: subprocess.Process):
        self._process = process

    @staticmethod
    async def spawn(host_addr, config_file: Optional[str] = None) -> "NSCAClient":
        args = list()

        def add_arg(args, switch, argument):
            if argument is not None:
                args.extend([switch, argument])

        add_arg(args, "-c", config_file)

        process = await asyncio.create_subprocess_exec(
            "send_nsca", "-H", host_addr, *args, stdin=asyncio.subprocess.PIPE
        )

        return NSCAClient(process)

    def send_report(self, report: NSCAReport):
        logger.debug(f"Sending NSCA report: {report!r}")
        self._process.stdin.write(str(report).encode("utf-8"))

    async def flush(self):
        self._process.stdin.write(b"\x17")
        await self._process.stdin.drain()

    def terminate(self):
        self._process.terminate()
