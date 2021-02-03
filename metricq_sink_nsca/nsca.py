# metricq-sink-nsca
# Copyright (C) 2021 ZIH, Technische Universitaet Dresden, Federal Republic of Germany
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

from asyncio.subprocess import PIPE, Process, create_subprocess_exec
from dataclasses import dataclass
from typing import List, TypedDict

from .logging import get_logger
from .state import State

logger = get_logger(__name__)


@dataclass
class NscaReport:
    host: str
    service: str
    state: State
    message: str


class NscaConfig(TypedDict, total=False):
    host: str
    port: int
    config_file: str
    executable: str


class Nsca:
    def __init__(self, host: str, port: int, config_file: str, executable: str):
        self.host = host
        self.port = port
        self.config_file = config_file
        self.executable = executable

    @staticmethod
    def from_config(config: NscaConfig) -> "Nsca":
        host = config.get("host")
        if host is None:
            raise ValueError(
                "Configuration must include the NSCA host address (`nsca.host`)"
            )

        port = config.get("port", 5667)
        config_file = config.get("config_file", "/etc/nsca/send_nsca.cfg")
        executable = config.get("executable", "/usr/sbin/send_nsca")

        return Nsca(host, port, config_file, executable)

    def __repr__(self) -> str:
        return f"<Nsca: addr='{self.host}:{self.port}', cfg={self.config_file!r}, exe={self.executable!r}>"

    async def send(self, reports: List[NscaReport]):
        input = self._encode_reports(reports)
        proc = await self._spawn_send_nsca()
        stdout, _stderr = await proc.communicate(input)

        assert proc.returncode is not None
        self._check_output(stdout, proc.returncode)

    def _command_line(self) -> List[str]:
        return [
            self.executable,
            "-H",
            self.host,
            "-p",
            str(self.port),
            "-c",
            self.config_file,
            "-d",
            ";",
        ]

    def _encode_reports(self, reports: List[NscaReport]) -> bytes:
        report_blocks: List[bytes] = []
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

        return b"\x17".join(report_blocks)

    async def _spawn_send_nsca(self) -> Process:
        return await create_subprocess_exec(
            *self._command_line(), stdin=PIPE, stdout=PIPE
        )

    def _check_output(self, stdout: bytes, returncode: int):
        logger.debug("send_nsca: exited ({})", returncode)
        if returncode != 0:
            try:
                msg = stdout.decode("ascii")
                for line in msg.splitlines():
                    logger.error("send_nsca: {}", line)
            except UnicodeError:
                logger.error("send_nsca: failed to decode output")
