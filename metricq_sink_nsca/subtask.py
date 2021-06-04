from asyncio import CancelledError, Task, create_task
from contextlib import suppress
from functools import partial
from typing import (
    Awaitable,
    Callable,
    Generic,
    NoReturn,
    Optional,
    Type,
    TypeVar,
    Union,
    overload,
)

from .logging import get_logger

logger = get_logger(__name__)

Class = TypeVar("Class", contravariant=True)

_NOT_FOUND = object()

__all__ = [
    "subtask",
    "Subtask",
]

SubtaskReturnType = Awaitable[Union[None, NoReturn]]


class Subtask(Generic[Class]):
    def __init__(self, task_factory: Callable[[], SubtaskReturnType], name: str):
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
        else:
            logger.debug("Cancelling subtask {!r} that never ran!", self)

    async def stop(self):
        self.cancel()
        if self._task is not None:
            logger.debug("Waiting for subtask {!r} to finish...", self)
            with suppress(CancelledError):
                await self._task

    def __repr__(self):
        return f"<Subtask: name={self._name!r} at {id(self):#x}>"


SubtaskMethod = Callable[[Class], SubtaskReturnType]


class SubtaskProxy(Generic[Class]):
    def __init__(self, method: SubtaskMethod[Class]):
        self._task_method: SubtaskMethod[Class] = method
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

    @overload
    def __get__(self, instance: Class, _objtype: Type[Class] = None) -> Subtask[Class]:
        ...

    @overload
    def __get__(self, instance: None, _objtype: Type[Class]) -> "SubtaskProxy[Class]":
        ...

    def __get__(self, instance: Optional[Class], _objtype=None):
        if instance is None:
            return self

        cls_name = type(instance).__name__

        try:
            assert self.attrname is not None
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


def subtask(f: SubtaskMethod[Class]) -> SubtaskProxy[Class]:
    return SubtaskProxy(f)
