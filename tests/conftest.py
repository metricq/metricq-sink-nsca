import pytest
from metricq.types import Timedelta, Timestamp


class Ticker:
    DEFAULT_DELTA = Timedelta.from_s(1)
    DEFAULT_START = Timestamp(0)

    def __init__(self, delta=DEFAULT_DELTA, start=DEFAULT_START):
        self.delta = delta
        self.start = start
        self.now = self.start

    def __next__(self):
        now = self.now
        self.now += self.delta
        return now

    def __iter__(self):
        return self


@pytest.fixture()
def ticker():
    return Ticker()
