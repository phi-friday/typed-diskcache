from __future__ import annotations

import inspect
from collections.abc import Callable
from contextlib import suppress
from typing import TYPE_CHECKING, Any, Generic

import anyio
import anyio.lowlevel
from typing_extensions import TypeVar

_T = TypeVar("_T", infer_variance=True)


class AsyncWrapper(Generic[_T]):
    if TYPE_CHECKING:

        def __new__(cls, value: _T, *, is_async: bool) -> _T: ...

    def __init__(self, value: _T, *, is_async: bool) -> None:
        self.__value = value
        self.__is_async = is_async

    def __getattr__(self, name: str) -> Any:
        value = getattr(self.__value, name)
        if callable(value) and name.startswith("a") and not self.__is_async:
            with suppress(AttributeError):
                value = getattr(self.__value, name[1:])
        if not callable(value):
            return value

        return unwrap(value)


def unwrap(func: Callable[..., Any]) -> Any:
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        value = func(*args, **kwargs)
        if inspect.isawaitable(value):
            return await value
        await anyio.lowlevel.checkpoint()
        return value

    return wrapper
