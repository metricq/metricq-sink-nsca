import logging

import pytest
from metricq import Timedelta, Timestamp

from metricq_sink_nsca.check import Check, CheckConfig, TvPair
from metricq_sink_nsca.override import Overrides
from metricq_sink_nsca.report_queue import Report, ReportQueue
from metricq_sink_nsca.state import State
from metricq_sink_nsca.value_check import ValueCheckConfig

DEFAULT_RESEND_INTERVAL = Timedelta.from_s(60)


@pytest.fixture
def config_minimal() -> CheckConfig:
    return {"metrics": ["test.foo", "test.bar"]}


@pytest.fixture
def check_kwargs():
    return {
        "name": "test",
        "overrides": Overrides.empty(),
        "report_queue": ReportQueue(),
        "resend_interval": DEFAULT_RESEND_INTERVAL,
    }


def test_check_config_minimal(config_minimal: CheckConfig, check_kwargs):
    check = Check.from_config(
        config=config_minimal,
        **check_kwargs,
    )

    assert check.config == config_minimal
    assert "test.foo" in check.metrics()
    assert "test.bar" in check.metrics()
    assert not check._has_timeout_checks()
    assert not check._has_value_checks()


def test_check_config_value_check_minimal(config_minimal: CheckConfig, check_kwargs):
    config = config_minimal.copy()
    config["warning_above"] = 0.0

    check = Check.from_config(config=config, **check_kwargs)

    assert check._timeout is None
    assert not check._has_timeout_checks()
    assert check._has_value_checks()


def test_check_config_timeout_check_minimal(config_minimal: CheckConfig, check_kwargs):
    """Specifying a `timeout` in the configuration creates active `TimeoutCheck`s for this `Check`."""
    config = config_minimal.copy()
    config["timeout"] = "30s"

    check = Check.from_config(config=config, **check_kwargs)

    assert check._timeout == Timedelta.from_s(30)
    assert check._has_timeout_checks()
    assert not check._has_value_checks()


def test_check_config_resend_interval(config_minimal: CheckConfig, check_kwargs):
    """A `resend_interval` in a check configuration overrides the global default."""
    config = config_minimal.copy()
    config["resend_interval"] = "10s"  # override
    check_kwargs["resend_interval"] = "60s"  # global default

    check = Check.from_config(config=config, **check_kwargs)

    assert check._resend_interval == Timedelta.from_s(10)


def test_check_config_full(config_minimal: CheckConfig, check_kwargs):
    value_check_config = ValueCheckConfig(
        critical_above=100.0,
        warning_above=80.0,
        warning_below=20.0,
        critical_below=0.0,
        ignore=[42.0],
    )
    config = CheckConfig(
        metrics=["test.foo", "test.bar"],
        timeout="30s",
        **value_check_config,
    )

    check = Check.from_config(config=config, **check_kwargs)

    assert check._has_timeout_checks()
    assert check._has_value_checks()


@pytest.fixture
def check():
    return Check(
        name="test",
        metrics={"foo"},
        report_queue=ReportQueue(),
        value_check=None,
        timeout=None,
        plugins={},
        transition_debounce_window=None,
        transition_postprocessor=None,
        resend_interval=Timedelta.from_s(60),
        config={},
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
