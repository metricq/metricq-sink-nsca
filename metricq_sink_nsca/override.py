from abc import ABC, abstractmethod
from typing import Any, Dict, List

from .logging import get_logger

logger = get_logger(__name__)


Metric = str


class PatternParseError(ValueError):
    def __init__(self, reason: str, *, pattern: str):
        super().__init__(f"Invalid pattern {pattern!r}: {reason}")


class MetricPattern(ABC):
    @abstractmethod
    def matches(self, metric: Metric) -> bool:
        raise NotImplementedError

    @staticmethod
    def parse(pattern: str) -> "MetricPattern":
        components = pattern.split(".")
        assert len(components) > 0, "str.split(sep) never results in 0 components"

        if any(frag == "" for frag in components):
            raise PatternParseError(
                "Metric names must have non-empty components separated by '.'",
                pattern=pattern,
            )

        # TODO: use '**' like in path globbing to match multiple fragments?
        WILDCARD_CHAR = "*"

        if WILDCARD_CHAR in components:
            prefix = components[:-1]
            last = components[-1]
            if last == WILDCARD_CHAR and not any(
                WILDCARD_CHAR in frag for frag in prefix
            ):
                return PrefixMatch(prefix=".".join(prefix + [""]))
            else:
                raise PatternParseError(
                    "Wildcard can only appear in the last position of the last component",
                    pattern=pattern,
                )
        elif any(WILDCARD_CHAR in c for c in components):
            raise PatternParseError(
                "Invalid pattern {pattern!r}: wildcards can only match a whole component",
                pattern=pattern,
            )
        else:
            return ExactMatch(name=pattern)


class PrefixMatch(MetricPattern):
    def __init__(self, *, prefix: str) -> None:
        self.prefix = prefix

    def matches(self, metric: Metric) -> bool:
        return metric.startswith(self.prefix)


class ExactMatch(MetricPattern):
    def __init__(self, *, name: str) -> None:
        self.name = name

    def matches(self, metric: Metric) -> bool:
        return self.name == metric


class MetricPatternSet:
    def __init__(self, *, patterns: List[MetricPattern]) -> None:
        self.patterns = patterns

    def __contains__(self, metric: Metric) -> bool:
        return any(pat.matches(metric) for pat in self.patterns)

    @staticmethod
    def empty() -> "MetricPatternSet":
        return MetricPatternSet(patterns=[])

    @staticmethod
    def from_config(patterns: List[str]) -> "MetricPatternSet":
        if not isinstance(patterns, list):
            raise TypeError(
                f"Expected a list of patterns, got {type(patterns).__name__!r}"
            )
        try:
            return MetricPatternSet(
                patterns=[MetricPattern.parse(pat) for pat in patterns]
            )
        except (ValueError, TypeError) as e:
            raise ValueError("Failed to parse list of metric patterns") from e


class Overrides:
    """Global overrides.

    Metrics whose name matches any of the patterns in `ignored_metrics` should not be subscribed to.
    """

    def __init__(self, *, ignored_metrics: MetricPatternSet) -> None:
        self.ignored_metrics = ignored_metrics

    @staticmethod
    def empty() -> "Overrides":
        """Create an empty section that specifies no overrides"""
        return Overrides(ignored_metrics=MetricPatternSet.empty())

    @staticmethod
    def from_config(config: Dict[str, Any]) -> "Overrides":
        """Parsed overrides of an `"overrides"` section from the configuration."""
        patterns = config.get("ignored_metrics", [])
        try:
            ignored_metrics = MetricPatternSet.from_config(patterns=patterns)
        except (ValueError, TypeError) as e:
            raise ValueError(
                f"Invalid list of ignored metrics (ignored_metrics={patterns!r})"
            ) from e

        return Overrides(ignored_metrics=ignored_metrics)
