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

from aionsca import State

import math
from typing import Optional, Iterable


class AbnormalRange:
    def __init__(self, low: float = -math.inf, high: float = math.inf):
        self.low = low
        self.high = high

        if self.low > self.high:
            raise ValueError(f"{self:r}: Boundaries must not cross")

    def is_empty(self):
        return self.low == -math.inf and self.high == math.inf

    def __repr__(self):
        return f"AbnormalRange(low={self.low}, high={self.high})"

    def __str__(self):
        if self.is_empty():
            return "never"
        elif self.low == -math.inf:
            return f"above {self.high}"
        elif self.high == math.inf:
            return f"below {self.low}"
        else:
            return f"below {self.low} or above {self.high}"

    def __contains__(self, value):
        return (value < self.low) or (self.high < value)


class ValueCheck:
    def __init__(
        self,
        warning_below: float = -math.inf,
        warning_above: float = math.inf,
        critical_below: float = -math.inf,
        critical_above: float = math.inf,
        ignore: Iterable[float] = set(),
    ):
        if not (critical_below <= warning_below < warning_above <= critical_above):
            raise ValueError(
                f"Warning range must be at least as strict as critical range: "
                f"warning_range=({warning_below}, {warning_above}), "
                f"critical_range=({critical_below}, {critical_above})"
            )

        self._warning_range = AbnormalRange(low=warning_below, high=warning_above)
        self._critical_range = AbnormalRange(low=critical_below, high=critical_above)
        self._ignore = set(ignore)

    @property
    def warning_range(self):
        return self._warning_range

    @property
    def critical_range(self):
        return self._critical_range

    def get_state(self, value: float) -> State:
        if value in self._ignore:
            return State.OK

        if value in self._critical_range:
            return State.CRITICAL
        elif value in self._warning_range:
            return State.WARNING
        else:
            return State.OK

    def __repr__(self):
        return (
            f"ValueCheck("
            f"warning_range={self._warning_range}, "
            f"critical_range={self._critical_range}, "
            f"ignore={self._ignore!r}"
            f")"
        )
