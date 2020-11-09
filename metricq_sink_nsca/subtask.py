from asyncio import Task, create_task
from functools import partial
from typing import Awaitable, Callable, Generic, Optional, TypeVar

from .logging import get_logger

logger = get_logger(__name__)

Class = TypeVar("Class")

_NOT_FOUND = object()

__all__ = [
    "subtask",
    "Subtask",
]


class Subtask(Generic[Class]):
    def __init__(self, task_factory: Callable[[], Awaitable[None]], name: str):
        self._task_factory = task_factory
        self._task: Optional[Task] = None
        self._name: str = name

    def start(self):
        if self._task is None:
            logger.debug("Starting subtask {!r}", self)
            task = self._task_factory()
            try:
                self._task = create_task(task, name=self._name)
            except TypeError:
                self._task = create_task(task)
        else:
            logger.warning("Subtask {!r} already started!", self)

    def cancel(self):
        if self._task is not None:
            logger.debug("Cancelling subtask {!r}", self)
            self._task.cancel()
            self._task = None

    def __repr__(self):
        return f"<Subtask: name={self._name!r} at {id(self):#x}>"


class SubtaskProxy(Generic[Class]):
    def __init__(self, method: Callable[[Class], Awaitable[None]]):
        self._task_method: Callable[[Class], Awaitable[None]] = method
        self.attrname: Optional[str] = None

        self.__doc__ = method.__doc__

    def __set_name__(self, owner: Class, name: str):
        if self.attrname is None:
            self.attrname = name
        elif self.attrname != name:
            raise TypeError(
                "Cannot assign the same subtask to two different names "
                f"({self.attrname!r} and {name!r})."
            )

    def __get__(self, instance: Optional[Class], _objtype=None):
        if instance is None:
            return self

        cls_name = type(instance).__name__

        try:
            task = instance.__dict__.get(self.attrname, _NOT_FOUND)
        except AttributeError:  # not all objects have __dict__ (e.g. class defines slots)
            msg = (
                f"No '__dict__' attribute on {cls_name!r} "
                f"instance to save {self.attrname!r} subtask."
            )
            raise TypeError(msg) from None

        if task is _NOT_FOUND:
            task = Subtask(
                task_factory=partial(self._task_method, instance),
                name=f"{cls_name}.{self.attrname}",
            )
            try:
                instance.__dict__[self.attrname] = task
            except TypeError:
                msg = (
                    f"The __dict__ attribute of {cls_name!r} "
                    "does not support item assignment"
                )
                raise RuntimeError(msg) from None
        return task


def subtask(f: Callable[[Class], Awaitable[None]]):
    return SubtaskProxy(f)
