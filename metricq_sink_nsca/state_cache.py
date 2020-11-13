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

from abc import ABC, abstractmethod
from bisect import bisect_left
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from dataclasses import replace as dataclass_replace
from typing import Dict, Iterable, Iterator, List, Optional, Set, Tuple, Union

from metricq.types import Timedelta, Timestamp

from .logging import get_logger
from .state import State

logger = get_logger(__name__)


@dataclass(order=True, frozen=True)
class StateTransition:
    """A state transition where up until ``time``, a metric resided in state
    ``state``.

    For any metric ``M``, we observe a series of state transitions.  Suppose
    there are two consecutive state transitions ``t1`` and ``t2``, i.e.

        ``t1.time < t2.time``

    We say that these transitions have _"last semantics"_, which means that at
    any time ``t1.time < t <= t2.time``, values of ``M`` were in state
    ``t2.state``.  In other words, the metric resides in some state ``t1.state``
    up until the time the new transition ``t2`` happens, at which point we know
    that ``t2.state`` occupied the _last time interval_.
    """

    time: Timestamp
    state: State = dataclass_field(compare=False, default=State.UNKNOWN)


class StateTransitionHistory:
    def __init__(self, time_window: Optional[Timedelta]):
        """A history of state transitions for some metric, spanning at most a
        duration of ``time_window``.

        It contains a point in time called 'epoch' that signifies when the state
        that the first transition switched from was entered.  In a graph (t[0]
        is the first transition, t[1] the second etc.):

                  ┌┄┄┄┄┄┄┄┄┄┄┄┄┄┄╮┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄╮    ⋯
                  │  t[0].state  │     t[1].state     │
           ⋯──────┴──────────────┴────────────────────┴────────────→
                epoch        t[0].time            t[1].time       time
        """

        # The list of state transitions for this metric.
        self._transitions: List[StateTransition] = list()

        # The point in time at which we assume the metric entered the state
        # given by the first transition ``self._transitions[0]``, if present.
        # This is necessary as transitions have last semantics, and we otherwise
        # had to assume that it was in this state since forever (which skews
        # statistics significantly, as you can imagine).
        self._epoch: Optional[Timestamp] = None

        # Use a sensible default time window for keeping past transitions.
        self._time_window: Timedelta
        if time_window is None:
            self._time_window = Timedelta.from_s(30)
        else:
            if time_window.ns > 0:
                self._time_window = time_window
            else:
                raise ValueError(
                    "State transition history time window must be a positive duration"
                )

    @property
    def epoch(self) -> Optional[Timestamp]:
        """The point in time at which we assume the metric entered the state given by the first transition, if present.

        As transitions have last semantics, without an epoch we would have to
        assume that a metric was in its first recorded state state since
        forever (which skews statistics significantly, as you can imagine).
        """
        return self._epoch

    @property
    def transitions(self) -> List[StateTransition]:
        """A (possibly empty) list of state transitions that occured so far.

        The first transition, farthest back in time, is recorded in :code:`self.transitions[0]`.
        The latest transitions is placed in :code:`self.transitions[-1]`.
        """
        return self._transitions

    def is_empty(self) -> bool:
        """A state transition history is empty if no epoch is set or no transitions have been inserted."""
        return self._epoch is None or len(self._transitions) < 1

    def insert(self, time: Timestamp, state: State):
        """Insert a transition that happened at ``time``, away from state
        ``state``, towards some other, unknown state.
        """
        if self._epoch is None:
            # If this is the first transition ever, we use it as an anchor point
            # in time and discard the state the metric came from.  When the next
            # transition is inserted, we know exactly how long the given state
            # was valid for.
            self._epoch = time
            return
        else:
            transition = StateTransition(time, state)
            if self._transitions:
                latest_transition = self._transitions[-1]
                if time <= latest_transition.time:
                    raise ValueError(
                        f"Times of state transitions must be strictly increasing: "
                        f"new transition at {time.posix_ns} is not after "
                        f"latest transition at {latest_transition.time.posix_ns}"
                    )
            self._transitions.append(transition)

        # Prune any transitions that happened outside of the time window in
        # which we are interested in, with respect to the newly inserted
        # transition.
        #
        # We use a binary search to find the index ``i`` of the first transition
        # ``t[i]`` that happened exactly at or after the cutoff.  We discard it
        # (and any older transitions), but keep its time as the new epoch.
        # This way we make sure that we never keep a history of transitions
        # spanning more than ``self._time_window``.
        history_cutoff = time - self._time_window
        if self._epoch > history_cutoff:
            # Transitions span less then ``self._time_window``, no need to
            # prune any of them.
            return
        else:
            i = bisect_left(self._transitions, StateTransition(time=history_cutoff))
            # The newly inserted transition at index ``len(self._transitions) - 1``
            # always happened after the cutoff, since ``self._time_window`` is
            # positive.  Therefore we will _always_ find a matching transition
            # within our history.
            assert i < len(self._transitions)

            # Save the new epoch and discard any transitions that are too old.
            self._epoch = self._transitions[i].time
            self._transitions = self._transitions[i + 1 :]

    def state_prevalences(self) -> Optional[Dict[State, float]]:
        """Return a ``dict`` where for each state, the share of time that a
        metric was in this state is a ``float`` between ``0.0`` and ``1.0``.
        """
        # We might only calculate prevalences of states if we already set an
        # epoch and there exists at least one transition.
        if self.is_empty():
            return None

        # Determine the first timestamp for calculating the cumulative duration
        # of each state.  Make sure it is at most self._time_window in the past,
        # wrt. the most recent transition in this history.
        latest_transition = self._transitions[-1]
        oldest_transition_time = max(
            latest_transition.time - self._time_window, self._epoch
        )

        total_duration: Timedelta = latest_transition.time - oldest_transition_time

        cumulative_durations = {state: Timedelta(0) for state in State}

        prev_time: Timestamp = oldest_transition_time
        current: StateTransition
        for current in self._transitions:
            cumulative_durations[current.state] += current.time - prev_time
            prev_time = current.time

        try:
            # Return the prevalence of each state as a percentage of the total
            # time spanned by all transitions.
            return {
                state: duration.ns / total_duration.ns
                for state, duration in cumulative_durations.items()
            }
        except ZeroDivisionError:
            return None

    def squashed(self) -> Iterator[Tuple[StateTransition, Timedelta]]:
        """Returns an iterator over the latest state transitions, together with
        the total duration of the transitioned-from state.

        The iterator yields transitions *newest to oldest*, not the other way around.
        Any transitions that did not actually change the state (i.e. where
        transitioned-from and transitioned-to state are the same) are squashed,
        their duration is added to the total duration.

        An empty history returns an empty iterator.

        A StateTransitionHistory does not squash states which do change state on insertion.
        Use this method if you want to answer questions like "How long has this
        metric been in the current state?" and "What was the the previous
        state, diffent from the current one, and how long did it last?":

        >>> # Answer the first question:
        >>> (current_state, duration) = next(history.squashed())
        (State.WARNING, <Timedelta ...>)

        >>> # ...and the second question:
        >>> (previous_state, duration) = next(next(history.squashed()))
        (State.OK, <Timedelta ...>)

        """
        if self.is_empty():
            return

        candidate_transition = dataclass_replace(self._transitions[-1])

        # Iterate over all transitions, in reverse order, starting with the second to last.
        # The `candidate_transition` marks the last transition in a chain of transitions
        # `S -> S -> ... -> S` for some state `S`.  We aim to squash this chain.
        # Skip a transition preceeding the candidate as long as it did not change state.
        # If it did, compute the total duration that the candidate state lasted
        # using the fact that state `S` was entered at `candidate.time` and
        # left at `candidate_transition.time`:
        #
        #    ┄┄┄┄┄┄╮┄┄┄┄┄┄┄╮
        #          │       │┄┄┄┄┄┄┄╮      ┄┄┄┄┄┄┄╮┄┄┄┄┄┄┄╮
        #          │   T   │   S   │  ⋯      S   │   S   │ ⋯
        #   ⋯──────┴───────┴───────┴─────────────┴───────┴──────→ time
        #                  ↑                             ↑
        #           transition.time            candidate_transition.time
        #
        # After that, recorded the current transition as a new candidate, since
        # it marks the time when the metric left some state; i.e. it is at the
        # start of its own chain of transitions `T -> T -> ... -> T`.
        for transition in self._transitions[-2::-1]:
            if transition.state == candidate_transition.state:
                continue
            else:
                yield (
                    candidate_transition,
                    candidate_transition.time - transition.time,
                )
                candidate_transition = transition
        else:
            yield (candidate_transition, candidate_transition.time - self.epoch)

    def __repr__(self):
        return f"{type(self).__name__}(window={self._time_window}, epoch={self._epoch}, transitions={self._transitions})"


class TransitionPostprocessor(ABC):
    @abstractmethod
    def process(
        self,
        metric: str,
        current_state: State,
        timestamp: Timestamp,
        history: StateTransitionHistory,
    ) -> State:
        return current_state


class TransitionDebounce(TransitionPostprocessor):
    def __init__(self, **_kwargs):
        pass

    def process(
        self,
        metric: str,
        current_state: State,
        timestamp: Timestamp,
        history: StateTransitionHistory,
    ) -> State:
        prevalences = history.state_prevalences()

        if prevalences is None:
            return current_state
        else:
            # Debounce state transitions by using the 'median' state,
            # sampled over the whole history.
            cumulative_prevalence = 0.0
            for some_state in State:
                cumulative_prevalence += prevalences[some_state]
                if cumulative_prevalence >= 0.5:
                    return some_state
            else:
                return current_state


class IgnoreShortTransitions(TransitionPostprocessor):
    def __init__(self, minimum_duration: Union[Timedelta, str], **_kwargs):
        self._minimum_duration = (
            Timedelta.from_string(minimum_duration)
            if isinstance(minimum_duration, str)
            else minimum_duration
        )

    def process(
        self,
        metric: str,
        current_state: State,
        _timestamp: Timestamp,
        history: StateTransitionHistory,
    ) -> State:
        try:
            squashed_states = history.squashed()
            (_, current_duration) = next(squashed_states)
            (previous_state, _) = next(squashed_states)

            if current_duration < self._minimum_duration:
                return previous_state
            else:
                current_state
        except StopIteration:
            return current_state


class SoftFail(TransitionPostprocessor):
    """Ignore a number of consecutive bad states

    Args:
        max_fail_count:
            The number of consecutive bad states that are ignored in favour of
            the preceeding good state.
            If, for example, set to :code:`max_fail_count=3` the first three
            :literal:`State.WARNING` states after a :literal:`State.OK` are
            ignored and :literal:`State.OK` is returned.
            The fourth :literal:`State.WARNING` state however is returned unaltered.
    """

    def __init__(self, max_fail_count: int, **_kwargs):
        self._max_fail_count = max_fail_count

    def process(
        self,
        metric: str,
        current_state: State,
        _timestamp: Timestamp,
        history: StateTransitionHistory,
    ) -> State:
        for transition, _ in zip(
            reversed(history.transitions), range(self._max_fail_count + 1)
        ):
            if transition.state < current_state:
                logger.debug(
                    f"Masking bad state {current_state.name} with recent good state {transition.state.name}"
                )
                return transition.state
        else:
            history_len = len(history.transitions)
            if history_len <= self._max_fail_count:
                logger.warning(
                    f"SoftFail is inconclusive: "
                    f"history of {metric} contains only {history_len} transitions, "
                    f"need at least {self._max_fail_count + 1}!"
                )

            if current_state != State.OK:
                logger.debug(
                    f"The last {self._max_fail_count} states were at least as bad as {current_state.name}, not masking!"
                )
            return current_state


class StateCache:
    def __init__(
        self,
        metrics: Iterable[str],
        transition_debounce_window: Optional[Timedelta] = None,
        transition_postprocessor: Optional[TransitionPostprocessor] = None,
    ):
        metrics = tuple(metrics)
        self._transition_histories: Dict[str, StateTransitionHistory] = {
            metric: StateTransitionHistory(time_window=transition_debounce_window)
            for metric in metrics
        }
        self._transition_postprocessor: TransitionPostprocessor = (
            transition_postprocessor or TransitionDebounce()
        )
        self._by_state: Dict[State, Set[str]] = {
            State.OK: set(),
            State.WARNING: set(),
            State.CRITICAL: set(),
            State.UNKNOWN: set(metrics),
        }
        self._timed_out: Dict[str, Optional[Timestamp]] = dict()

    def update_state(self, metric: str, timestamp: Timestamp, state: State):
        """Update the cached state of a metric

        This implicitly marks a metric as not being timed out.
        """
        try:
            metric_history = self._transition_histories[metric]
        except KeyError:
            raise ValueError(
                f"{type(self).__name__} not set up to track state of metric {metric}"
            )

        try:
            metric_history.insert(time=timestamp, state=state)
        except ValueError:
            raise ValueError(f"Failed to update state history of {metric!r}")

        postprocessed_state = self._transition_postprocessor.process(
            metric, state, timestamp, metric_history
        )
        if postprocessed_state != state:
            logger.info(
                f"{type(self._transition_postprocessor).__name__}: "
                f"adjusted transition for {metric!r}: "
                f"{state} -> {postprocessed_state}"
            )
        self._update_cache(metric, postprocessed_state)

    def _update_cache(self, metric: str, state: State):
        self._timed_out.pop(metric, None)
        for metrics in self._by_state.values():
            if metric in metrics:
                metrics.remove(metric)
                break
        else:
            raise ValueError(
                f"StateCache not setup to track state of metric {metric!r}"
            )

        try:
            self._by_state[state].add(metric)
        except KeyError as e:
            raise ValueError(
                f"Not a valid state: {state!r} ({type(state).__qualname__})"
            ) from e

    def set_timed_out(self, metric: str, last_timestamp: Optional[Timestamp]):
        self._timed_out[metric] = last_timestamp

    def __repr__(self):
        return f"StateCache(transitions={self._transition_histories}, timed_out={self._timed_out})"

    def overall_state(self) -> State:
        """Return the most severe state of any cached metric

        If any of the contained metrics are critical, return State.CRITICAL,
        if any are warning, return State.WARNING etc.

        Should any metrics be in an unknown state, return State.UNKNOWN. This
        happens if they were never updated via update_state().
        """
        if self._timed_out:
            return State.CRITICAL

        if self._by_state[State.UNKNOWN]:
            return State.UNKNOWN
        elif self._by_state[State.CRITICAL]:
            return State.CRITICAL
        elif self._by_state[State.WARNING]:
            return State.WARNING
        elif self._by_state[State.OK]:
            return State.OK
        else:
            return State.UNKNOWN

    def __getitem__(self, state: State) -> Set[str]:
        return self._by_state[state]

    @property
    def timed_out(self) -> Dict[str, Optional[Timestamp]]:
        return self._timed_out
