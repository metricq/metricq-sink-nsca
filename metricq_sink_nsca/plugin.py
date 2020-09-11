import importlib
from abc import ABC, abstractmethod
from types import ModuleType
from typing import Callable, Iterable, Set

from metricq import Timestamp

from .state import State


class Plugin(ABC):
    """Base class exposing the interface to a plugin instance loaded from a file."""

    @abstractmethod
    def check(
        self,
        metric: str,
        timestamp: Timestamp,
        value: float,
        current_state: State,
        *args,
        **_kwargs,
    ) -> State:
        """Perform an arbitrary check on a metric.

        This is the heart of the plugin.  Any time a metric monitored by a
        check receives a new value, this method is called.  It should return a
        new state based on value, timestamp and current state of the metric, as
        determined by the value check logic.

        If multiple plugins for the same check report different states for a
        metric, the most severe state is reported as the final state for this
        metric.

        :param metric:
            The name of the metric that this check should provide a new state for.
        :param timestamp:
            Timestamp of the current value.
        :param value:
            The value of `metric` at time `timestamp`.
        :param current_state:
            The current state, as determined by value checks.
        """
        raise NotImplementedError

    @abstractmethod
    def extra_metrics(self) -> Iterable[str]:
        """Returns an iterable of metric names that should be subscribed to in
        addition to the metrics already monitored by this check.

        This method is called right after initializing the plugin.

        These metrics are not checked by the usual value/timeout check logic,
        but are forwarded to the plugin via :py:meth:`on_extra_metric`.  This
        can be used to provide additional context to the plugin check logic,
        e.g. to only report abnormal states for a metric if another metric
        satisfies a certain condition.
        """
        raise NotImplementedError

    @abstractmethod
    def on_extra_metric(
        self, metric: str, timestamp: Timestamp, value: float, *args, **_kwargs
    ):
        """Receive a new (time, value)-pair for an metric declared by
        :py:meth:`extra_metrics`.
        """
        raise NotImplementedError


EntryPointType = Callable[[str, dict, Set[str]], Plugin]


def load(name: str, file: str, metrics: Set[str], config: dict) -> Plugin:
    """Load a plugin file for a check.

    :param name:
        Name of the plugin instance to load.  Only used for logging, but unique
        for each plugin loaded for a check:  It is the configuration key at
        `plugins.<name>` in the configuration of a check.  Should be a valid
        python module-identifier, i.e. match `/[a-z_]+/`.
    :param file:
        File system path to the plugin `.py`-file to load as a plugin, as found
        under `plugins.<name>.file` in the configuration for a check.
    :param metrics:
        The set of metrics monitored by this check.
    :param config:
        Optional arbitrary configuration data for the plugin instance, as found
        under `plugins.<name>.config` in the configuration for a check.
    """
    module_spec = importlib.util.spec_from_file_location(f"{__name__}.{name}", file)
    module: ModuleType = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    entry_point: EntryPointType = module.get_plugin
    return entry_point(name, config, metrics)
