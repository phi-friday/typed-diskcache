from __future__ import annotations

import inspect
import threading
from contextlib import contextmanager
from contextvars import ContextVar, Token, copy_context
from functools import partial, wraps
from typing import TYPE_CHECKING, Any, overload

from typing_extensions import TypeVar

from typed_diskcache.core.const import DEFAULT_LOG_CONTEXT, DEFAULT_LOG_THREAD

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

__all__ = ["log_context", "override_context", "context"]

_F = TypeVar("_F", bound="Callable[..., Any]", infer_variance=True)

log_context: ContextVar[tuple[str, int]] = ContextVar(
    "log_thread_context", default=(DEFAULT_LOG_CONTEXT, DEFAULT_LOG_THREAD)
)
"""The context variable to store the log context for the current thread."""
override_context: ContextVar[tuple[str, int] | None] = ContextVar(
    "override_context", default=None
)
"""
The context variable to store the override context for the current thread.
If set, it will be used instead of the log context.
"""


@contextmanager
def enter_context(
    context: str, var: ContextVar[tuple[str, int]] | ContextVar[tuple[str, int] | None]
) -> Generator[None, None, None]:
    thread_id = threading.get_native_id()
    log_token: Token[Any] | None = None
    try:
        log_token = var.set((context, thread_id))
        yield
    finally:
        if log_token is not None:
            var.reset(log_token)


@overload
def context(func_or_context: str) -> Callable[[_F], _F]: ...
@overload
def context(func_or_context: _F) -> _F: ...
@overload
def context(func_or_context: str, *, override: bool = ...) -> Callable[[_F], _F]: ...
@overload
def context(func_or_context: _F, *, override: bool = ...) -> _F: ...
@overload
def context(
    func_or_context: _F | str, *, override: bool = ...
) -> _F | Callable[[_F], _F]: ...
def context(
    func_or_context: _F | str, *, override: bool = False
) -> _F | Callable[[_F], _F]:
    """Decorator to set the log context for the decorated function.

    Args:
        func_or_context: The function to decorate or the context to set.
        override: If True, use override_context instead of log_context.
            Defaults to False.

    Returns:
        The decorated function or the decorator.
    """
    if not isinstance(func_or_context, str):
        name = getattr(func_or_context, "__qualname__", func_or_context.__name__)
        return _context(func_or_context, name=name, override=override)

    return partial(_context, name=func_or_context, override=override)


def _context(func: _F, *, name: str, override: bool) -> _F:
    var = override_context if override else log_context

    if inspect.iscoroutinefunction(func):

        @wraps(func)
        async def async_wrapped(*args: Any, **kwargs: Any) -> Any:
            with enter_context(name, var):
                local_context = copy_context()
                return await local_context.run(func, *args, **kwargs)

        return async_wrapped  # pyright: ignore[reportReturnType]

    @wraps(func)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        with enter_context(name, var):
            local_context = copy_context()
            return local_context.run(func, *args, **kwargs)

    return wrapped  # pyright: ignore[reportReturnType]
