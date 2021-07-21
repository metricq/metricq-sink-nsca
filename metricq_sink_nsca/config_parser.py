from typing import Optional, overload

from metricq.types import Timedelta

Metric = str
DurationStr = str


@overload
def parse_timedelta(
    duration: Optional[DurationStr], default: None = None
) -> Optional[Timedelta]:
    ...


@overload
def parse_timedelta(duration: Optional[DurationStr], default: Timedelta) -> Timedelta:
    ...


def parse_timedelta(
    duration: Optional[DurationStr], default: Optional[Timedelta] = None
) -> Optional[Timedelta]:
    if duration is None:
        return default
    else:
        return Timedelta.from_string(duration)
