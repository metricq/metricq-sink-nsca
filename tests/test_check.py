import logging
from typing import Any, Dict

import pytest
from metricq import Timedelta, Timestamp

from metricq_sink_nsca.check import Check, TvPair
from metricq_sink_nsca.report_queue import Report, ReportQueue
from metricq_sink_nsca.state import State

from tests.conftest import Ticker


@pytest.fixture
def check_default_args() -> Dict[str, Any]:
    return dict(
        name="test",
        metrics=["foo"],
        report_queue=ReportQueue(),
        value_constraints=None,
        resend_interval=Timedelta.from_s(60),
    )


@pytest.fixture
def check(check_default_args):
    return Check(**check_default_args)


@pytest.fixture
def check_with_ignore_update_errors(check_default_args: dict) -> Check:
    return Check(**check_default_args, ignore_update_errors=True)


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


def test_check_ignore_update_error(
    check_with_ignore_update_errors: Check,
    ticker: Ticker,
    caplog: pytest.LogCaptureFixture,
):
    """Assert that a check that has `ignore_update_errors` set will not generate CRITICAL reports for non-monotonic metrics."""
    check = check_with_ignore_update_errors
    report_queue = check._report_queue

    epoch = next(ticker)

    # Make sure the internal state cache has an epoch set
    check.check("foo", tv_pairs=[TvPair(epoch, 0)])
    assert report_queue._queue.get_nowait().state == State.OK

    # If ignore_update_errors is set, tv_pairs with duplicate/past timestamps should be ignored.
    with caplog.at_level(logging.ERROR):
        duplicate = TvPair(next(ticker), 0)
        check.check("foo", tv_pairs=[duplicate, duplicate])

        # Make sure a log message at level ERROR is generated
        assert any(
            "duplicate" in message and level == logging.ERROR
            for logger, level, message in caplog.record_tuples
        )

        # Assert that no report was generated for these values
        assert check._report_queue._queue.empty()
