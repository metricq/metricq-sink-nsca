import logging

import pytest
from metricq import Timedelta, Timestamp

from metricq_sink_nsca.check import Check, TvPair
from metricq_sink_nsca.report_queue import Report, ReportQueue
from metricq_sink_nsca.state import State


@pytest.fixture
def check():
    return Check(
        name="test",
        metrics=["foo"],
        report_queue=ReportQueue(),
        value_constraints=None,
        resend_interval=Timedelta.from_s(60),
    )


def test_check_internal_exception_report(check):
    errmsg = "check_metric_raising"

    def check_metric_raising(*args, **kwargs):
        raise ValueError(errmsg)

    check.check_metric = check_metric_raising

    check.check("foo", tv_pairs=[TvPair(Timestamp(0), 0.0)])

    report: Report = check._report_queue._queue.get_nowait()

    assert report.service == check._name
    assert report.state == State.CRITICAL
    assert errmsg in report.message


def test_check_internal_chained_exception_report(check):
    errmsg_toplevel = "top-level exception"
    errmsg_cause = "chained exception"

    def check_metric_raising(*args, **kwargs):
        try:
            raise RuntimeError(errmsg_cause)
        except RuntimeError as e:
            raise RuntimeError(errmsg_toplevel) from e

    check.check_metric = check_metric_raising

    check.check("foo", tv_pairs=[TvPair(Timestamp(0), 0.0)])

    report: Report = check._report_queue._queue.get_nowait()

    assert report.service == check._name
    assert report.state == State.CRITICAL

    header, *causes = report.message.splitlines()

    assert errmsg_toplevel in header

    assert len(causes) == 1
    assert "caused by:" in causes[0]
    assert errmsg_cause in causes[0]


def test_check_internal_exception_log_entry(check, caplog):
    errmsg = "check_metric_raising"

    def check_metric_raising(*args, **kwargs):
        raise ValueError(errmsg)

    check.check_metric = check_metric_raising

    with caplog.at_level(logging.ERROR):
        check.check("foo", tv_pairs=[TvPair(Timestamp(0), 0.0)])

        assert errmsg in caplog.text

        assert any(
            "Unhandled exception" in message
            for logger, level, message in caplog.record_tuples
        )
