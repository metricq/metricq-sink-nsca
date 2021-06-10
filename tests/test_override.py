from typing import Type

import pytest

from metricq_sink_nsca.override import (
    ExactMatch,
    MetricPattern,
    PatternParseError,
    PrefixMatch,
)


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        ("foo", ExactMatch),
        ("foo.bar", ExactMatch),
        ("foo.*", PrefixMatch),
        ("foo.bar.*", PrefixMatch),
    ],
)
def test_pattern_parsed_type(pattern: str, expected: Type[MetricPattern]):
    assert type(MetricPattern.parse(pattern)) is expected


@pytest.mark.parametrize(
    "invalid_pattern",
    [
        "",  # empty string is not a valid metric name
        "foo.*.bar",  # arbitrary wildcard patterns not yet supported
        "foo.*.bar.*",  # as above
        "foo..bar",  # metric names have non-empty components
        "foo.bar*",  # cannot match part of a component
    ],
)
def test_invalid_patterns(invalid_pattern: str):
    with pytest.raises(PatternParseError):
        MetricPattern.parse(invalid_pattern)


@pytest.mark.parametrize(
    "metric",
    [
        "foo",
        "foo.bar",
    ],
)
def test_exact_match(metric: str):
    exact_match = MetricPattern.parse(metric)
    assert isinstance(exact_match, ExactMatch)
    assert exact_match.matches(metric)


@pytest.mark.parametrize(
    ("metric", "no_match"),
    [
        ("foo", "bar"),
        ("foo", "foo."),
        ("foo", ".foo"),
        ("foo", "bar.foo"),
        ("foo.bar", "foo"),
        ("foo.bar", "foo."),
    ],
)
def test_no_exact_match(metric: str, no_match: str):
    assert not MetricPattern.parse(metric).matches(no_match)


@pytest.mark.parametrize(
    ("pattern", "metric"),
    [
        ("foo.*", "foo.bar"),
        ("foo.*", "foo.bar.baz"),  # currently, wildcards match more than one component
        ("foo.bar.*", "foo.bar.baz"),
    ],
)
def test_prefix_match(pattern: str, metric: str):
    prefix_match = MetricPattern.parse(pattern)
    assert isinstance(prefix_match, PrefixMatch)
    assert prefix_match.matches(metric)
