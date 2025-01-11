# ruff: noqa: PLR0913
from __future__ import annotations

import inspect
import math
import random
import threading
import time
from collections.abc import Awaitable, Callable, Coroutine, Iterable
from concurrent.futures import Future, wait
from functools import partial
from itertools import chain
from typing import TYPE_CHECKING, Any, Generic, Protocol, overload
from weakref import WeakSet

from pydantic import TypeAdapter
from typing_extensions import ParamSpec, TypeVar, override

from typed_diskcache import exception as te
from typed_diskcache.core.const import ENOVAL
from typed_diskcache.interface.cache import CacheProtocol
from typed_diskcache.log import get_logger
from typed_diskcache.utils.dependency import validate_installed

if TYPE_CHECKING:
    from typed_diskcache.interface.cache import CacheProtocol

__all__ = ["memoize", "memoize_stampede"]

_T = TypeVar("_T", infer_variance=True)
_P = ParamSpec("_P")

_STAMPEDE_ADAPTER = TypeAdapter(tuple[Any, float])
logger = get_logger()


class Memoized(Generic[_P, _T]):
    __slots__ = (
        "_base",
        "_cache",
        "_exclude",
        "_expire",
        "_func",
        "_include",
        "_tags",
        "_typed",
    )

    def __init__(
        self,
        *,
        cache: CacheProtocol,
        func: Callable[_P, _T],
        base: str,
        typed: bool,
        expire: float | None,
        tags: frozenset[str],
        include: frozenset[str | int],
        exclude: frozenset[str | int],
    ) -> None:
        self._cache = cache
        self._func = func
        self._base = base
        self._typed = typed
        self._expire = expire
        self._tags = tags
        self._include = include
        self._exclude = exclude

    def __call__(self, *args: _P.args, **kwargs: _P.kwargs) -> _T:
        key = self.cache_key(*args, **kwargs)
        container = self._cache.get(key, retry=True)
        if not container.default:
            return container.value

        value = self._func(*args, **kwargs)
        if self._expire is None or self._expire > 0:
            self._cache.set(
                key, value, expire=self._expire, tags=self._tags, retry=True
            )
        return value

    @property
    def __wrapped__(self) -> Callable[_P, _T]:
        return self._func

    def cache_key(self, *args: _P.args, **kwargs: _P.kwargs) -> tuple[Any, ...]:
        return args_to_key(
            base=self._base,
            args=args,
            kwargs=kwargs,
            typed=self._typed,
            include=self._include,
            exclude=self._exclude,
        )


class AsyncMemoized(Memoized[_P, Coroutine[Any, Any, _T]], Generic[_P, _T]):
    @override
    def __init__(
        self,
        *,
        cache: CacheProtocol,
        func: Callable[_P, Coroutine[Any, Any, _T]],
        base: str,
        typed: bool,
        expire: float | None,
        tags: frozenset[str],
        include: frozenset[str | int],
        exclude: frozenset[str | int],
    ) -> None:
        super().__init__(
            cache=cache,
            func=func,
            base=base,
            typed=typed,
            expire=expire,
            tags=tags,
            include=include,
            exclude=exclude,
        )

    @override
    async def __call__(self, *args: _P.args, **kwargs: _P.kwargs) -> _T:
        key = self.cache_key(*args, **kwargs)
        container = await self._cache.aget(key, retry=True)
        if not container.default:
            return container.value

        value = await self._func(*args, **kwargs)
        if self._expire is None or self._expire > 0:
            await self._cache.aset(
                key, value, expire=self._expire, tags=self._tags, retry=True
            )
        return value

    @property
    @override
    def __wrapped__(self) -> Callable[_P, Coroutine[Any, Any, _T]]:
        return self._func


class Timer(Generic[_P, _T]):
    __slots__ = ("_func",)

    def __init__(self, func: Callable[_P, _T]) -> None:
        self._func = func

    def __call__(self, *args: _P.args, **kwargs: _P.kwargs) -> tuple[_T, float]:
        start = time.monotonic()
        value = self._func(*args, **kwargs)
        delta = time.monotonic() - start
        return value, delta


class AsyncTimer(Generic[_P, _T]):
    __slots__ = ("_func",)

    def __init__(self, func: Callable[_P, Awaitable[_T]]) -> None:
        self._func = func

    async def __call__(self, *args: _P.args, **kwargs: _P.kwargs) -> tuple[_T, float]:
        start = time.monotonic()
        value = await self._func(*args, **kwargs)
        delta = time.monotonic() - start
        return value, delta


class MemoizedStampede(Memoized[_P, _T], Generic[_P, _T]):
    __slots__ = (*Memoized.__slots__, "_beta", "_futures")

    @override
    def __init__(
        self,
        *,
        cache: CacheProtocol,
        func: Callable[_P, _T],
        base: str,
        typed: bool,
        expire: float | None,
        tags: frozenset[str],
        include: frozenset[str | int],
        exclude: frozenset[str | int],
        beta: float = 1,
    ) -> None:
        super().__init__(
            cache=cache,
            func=func,
            base=base,
            typed=typed,
            expire=expire,
            tags=tags,
            include=include,
            exclude=exclude,
        )
        self._beta = beta
        self._futures: set[Future[Any]] = set()

    @override
    def __call__(self, *args: _P.args, **kwargs: _P.kwargs) -> _T:
        key = self.cache_key(*args, **kwargs)
        container = self._cache.get(key, retry=True)

        if container.default:
            timer = Timer(self._func)
            value = timer(*args, **kwargs)
            self._cache.set(
                key, value, expire=self._expire, tags=self._tags, retry=True
            )
            return value[0]

        value, delta = validate_stampede_value(container.value)
        now = time.time()
        ttl = container.expire_time or 0 - now
        if (-delta * self._beta * math.log(random.random())) < ttl:  # noqa: S311
            return value

        thread_key: tuple[Any, ...] = tuple((*key, ENOVAL))  # noqa: C409
        thread_added = self._cache.add(thread_key, None, expire=delta, retry=True)

        if not thread_added:
            return value

        future: Future[Any] = Future()
        thread = threading.Thread(
            target=thread_recompute,
            args=(
                future,
                self._cache,
                key,
                self._func,
                self._expire,
                self._tags,
                *args,
            ),
            kwargs=kwargs.copy(),
        )
        thread.daemon = True
        self._futures.add(future)
        future.add_done_callback(self._futures.discard)
        thread.start()

        return value

    @property
    def futures(self) -> WeakSet[Future[Any]]:
        return WeakSet(self._futures)

    def wait(self) -> None:
        futures = list(self._futures)
        if not futures:
            return
        wait(futures)


class AsyncMemoizedStampede(
    MemoizedStampede[_P, Coroutine[Any, Any, _T]], Generic[_P, _T]
):
    @override
    def __init__(
        self,
        *,
        cache: CacheProtocol,
        func: Callable[_P, Coroutine[Any, Any, _T]],
        base: str,
        typed: bool,
        expire: float | None,
        tags: frozenset[str],
        include: frozenset[str | int],
        exclude: frozenset[str | int],
        beta: float = 1,
    ) -> None:
        super().__init__(
            cache=cache,
            func=func,
            base=base,
            typed=typed,
            expire=expire,
            tags=tags,
            include=include,
            exclude=exclude,
            beta=beta,
        )

    @override
    async def __call__(self, *args: _P.args, **kwargs: _P.kwargs) -> _T:
        key = self.cache_key(*args, **kwargs)
        container = self._cache.get(key, retry=True)

        if container.default:
            timer = AsyncTimer(self._func)
            value = await timer(*args, **kwargs)
            await self._cache.aset(
                key, value, expire=self._expire, tags=self._tags, retry=True
            )
            return value[0]

        value, delta = validate_stampede_value(container.value)
        now = time.time()
        ttl = container.expire_time or 0 - now
        if (-delta * self._beta * math.log(random.random())) < ttl:  # noqa: S311
            return value

        thread_key: tuple[Any, ...] = tuple((*key, ENOVAL))  # noqa: C409
        thread_added = await self._cache.aadd(
            thread_key, None, expire=delta, retry=True
        )

        if not thread_added:
            return value

        future: Future[Any] = Future()
        thread = threading.Thread(
            target=async_thread_recompute,
            args=(
                future,
                self._cache,
                key,
                self._func,
                self._expire,
                self._tags,
                *args,
            ),
            kwargs=kwargs.copy(),
        )
        thread.daemon = True
        self._futures.add(future)
        future.add_done_callback(self._futures.discard)
        thread.start()

        return value


class MemoizedDecorator(Protocol):
    @overload
    def __call__(
        self, func: Callable[_P, Coroutine[Any, Any, _T]]
    ) -> AsyncMemoized[_P, _T]: ...
    @overload
    def __call__(self, func: Callable[_P, _T]) -> Memoized[_P, _T]: ...
    @overload
    def __call__(self, func: Callable[_P, Any]) -> Memoized[_P, Any]: ...
    def __call__(self, func: Callable[_P, Any]) -> Memoized[_P, Any]: ...


class MemoizedStampedeDecorator(Protocol):
    @overload
    def __call__(
        self, func: Callable[_P, Coroutine[Any, Any, _T]]
    ) -> AsyncMemoizedStampede[_P, _T]: ...
    @overload
    def __call__(self, func: Callable[_P, _T]) -> MemoizedStampede[_P, _T]: ...
    @overload
    def __call__(self, func: Callable[_P, Any]) -> MemoizedStampede[_P, Any]: ...
    def __call__(self, func: Callable[_P, Any]) -> MemoizedStampede[_P, Any]: ...


def memoize(
    cache: CacheProtocol,
    name: str | None = None,
    *,
    typed: bool = False,
    expire: float | None = None,
    tags: str | Iterable[str] | None = None,
    include: Iterable[str | int] = (),
    exclude: Iterable[str | int] = (),
) -> MemoizedDecorator:
    """Memoizing cache decorator.

    Decorator to wrap callable with memoizing function using cache.
    Repeated calls with the same arguments will lookup result in cache and
    avoid function evaluation.

    If name is set to None (default), the callable name will be determined
    automatically.

    When expire is set to zero, function results will not be set in the
    cache. Cache lookups still occur, however.

    If typed is set to True, function arguments of different types will be
    cached separately. For example, f(3) and f(3.0) will be treated as
    distinct calls with distinct results.

    The original underlying function is accessible through the `__wrapped__`
    attribute. This is useful for introspection, for bypassing the cache,
    or for rewrapping the function with a different cache.

    ```python
    from typed_diskcache import Cache
    from typed_diskcache.utils.memo import memoize_stampede


    cache = Cache()

    @cache.memoize(expire=1, tag="fib")
    def fibonacci(number):
        if number == 0:
            return 0
        elif number == 1:
            return 1
        else:
            return fibonacci(number - 1) + fibonacci(number - 2)


    print(fibonacci(100))
    # 354224848179261915075
    ```

    An additional `cache_key` method can be used to generate the
    cache key used for the given arguments.

    ```python
    key = fibonacci.cache_key(100)
    print(cache[key])
    # 354224848179261915075
    ```

    Remember to call memoize when decorating a callable. If you forget,
    then a TypeError will occur. Note the lack of parenthenses after
    memoize below:

    ```python
    @cache.memoize
    def test():
        pass
    ```

    Args:
        cache: cache to store callable arguments and return values
        name: name given for callable (default None, automatic)
        typed: cache different types separately (default False)
        expire: seconds until arguments expire (default None, no expiry)
        tags: text to associate with arguments (default None)
        include: positional or keyword args to include (default ())
        exclude: positional or keyword args to exclude (default ())

    Returns:
        memoized callable decorator
    """
    tags = frozenset(tags or ())
    include = frozenset(include)
    exclude = frozenset(exclude)

    def decorator(func: Callable[..., Any]) -> Memoized[..., Any]:
        base = name or full_name(func)
        memoized = AsyncMemoized if inspect.iscoroutinefunction(func) else Memoized
        return memoized(
            cache=cache,
            func=func,
            base=base,
            typed=typed,
            expire=expire,
            tags=tags,
            include=include,
            exclude=exclude,
        )

    return decorator  # pyright: ignore[reportReturnType]


def memoize_stampede(
    cache: CacheProtocol,
    name: str | None = None,
    *,
    typed: bool = False,
    expire: float | None = None,
    tags: str | Iterable[str] | None = None,
    include: Iterable[str | int] = (),
    exclude: Iterable[str | int] = (),
    beta: float = 1,
) -> MemoizedStampedeDecorator:
    """Memoizing cache decorator with cache stampede protection.

    Cache stampedes are a type of system overload that can occur when parallel
    computing systems using memoization come under heavy load. This behaviour
    is sometimes also called dog-piling, cache miss storm, cache choking, or
    the thundering herd problem.

    The memoization decorator implements cache stampede protection through
    early recomputation. Early recomputation of function results will occur
    probabilistically before expiration in a background thread of
    execution. Early probabilistic recomputation is based on research by
    Vattani, A.; Chierichetti, F.; Lowenstein, K. (2015), Optimal Probabilistic
    Cache Stampede Prevention, VLDB, pp. 886-897, ISSN 2150-8097

    If name is set to None (default), the callable name will be determined
    automatically.

    If typed is set to True, function arguments of different types will be
    cached separately. For example, f(3) and f(3.0) will be treated as distinct
    calls with distinct results.

    The original underlying function is accessible through the `__wrapped__`
    attribute. This is useful for introspection, for bypassing the cache, or
    for rewrapping the function with a different cache.

    ```python
    from typed_diskcache import Cache
    from typed_diskcache.utils.memo import memoize_stampede


    cache = Cache()

    @memoize_stampede(cache, expire=1)
    def fib(number):
        if number == 0:
            return 0
        elif number == 1:
            return 1
        else:
            return fib(number - 1) + fib(number - 2)


    print(fib(100))
    # 354224848179261915075
    ```

    An additional `cache_key` method can be used to generate the cache
    key used for the given arguments.

    ```python
    key = fib.cache_key(100)
    del cache[key]
    ```

    Remember to call memoize when decorating a callable. If you forget, then a
    TypeError will occur.

    Args:
        cache: cache to store callable arguments and return values
        name: name given for callable (default None, automatic)
        typed: cache different types separately (default False)
        expire: seconds until arguments expire
        tags: text to associate with arguments (default None)
        include: positional or keyword args to include (default ())
        exclude: positional or keyword args to exclude (default ())
        beta: cache stampede protection factor (default 1)

    Returns:
        memoized callable decorator
    """
    tags = frozenset(tags or ())
    include = frozenset(include)
    exclude = frozenset(exclude)

    def decorator(func: Callable[..., Any]) -> MemoizedStampede[..., Any]:
        base = name or full_name(func)
        memoized = (
            AsyncMemoizedStampede
            if inspect.iscoroutinefunction(func)
            else MemoizedStampede
        )
        return memoized(
            cache=cache,
            func=func,
            base=base,
            typed=typed,
            expire=expire,
            tags=tags,
            include=include,
            exclude=exclude,
            beta=beta,
        )

    return decorator  # pyright: ignore[reportReturnType]


def full_name(func: Callable[..., Any]) -> str:
    name = getattr(func, "__qualname__", func.__name__)
    return f"{func.__module__}.{name}"


def args_to_key(
    *,
    base: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    typed: bool,
    include: frozenset[str | int],
    exclude: frozenset[str | int],
) -> tuple[Any, ...]:
    args = tuple(
        arg for index, arg in enumerate(args) if check_select(index, include, exclude)
    )
    key: Iterable[Any] = chain((base,), args, (None,))

    if typed:
        key = chain(key, tuple(type(arg) for arg in args), (None,))

    if kwargs:
        kwargs = {
            key: val
            for key, val in kwargs.items()
            if check_select(key, include, exclude)
        }
        sorted_items = sorted(kwargs.items())

        key = chain(key, sorted_items, (None,))

        if typed:
            key = chain(key, tuple(type(val) for _, val in sorted_items), (None,))

    return tuple(key)


def validate_stampede_value(value: Any) -> tuple[Any, float]:
    try:
        return _STAMPEDE_ADAPTER.validate_python(value)
    except ValueError as exc:
        raise te.TypedDiskcacheTypeError("stampede value is not a tuple") from exc


def thread_recompute(
    future: Future[Any],
    cache: CacheProtocol,
    key: Any,
    func: Callable[_P, Any],
    expire: float | None,
    tags: frozenset[str],
    *args: _P.args,
    **kwargs: _P.kwargs,
) -> None:
    try:
        timer = Timer(func)
        value = timer(*args, **kwargs)
        cache.set(key, value, expire=expire, tags=tags, retry=True)
    except BaseException as exc:  # noqa: BLE001
        future.set_exception(exc)
    else:
        future.set_result(None)


def async_thread_recompute(
    future: Future[Any],
    cache: CacheProtocol,
    key: Any,
    func: Callable[_P, Any],
    expire: float | None,
    tags: frozenset[str],
    *args: _P.args,
    **kwargs: _P.kwargs,
) -> None:
    validate_installed("anyio", "Consider installing extra `asyncio`.")
    import anyio

    try:
        timer = AsyncTimer(func)
        value = anyio.run(partial(timer, *args, **kwargs))
        cache.set(key, value, expire=expire, tags=tags, retry=True)
    except BaseException as exc:  # noqa: BLE001
        future.set_exception(exc)
    else:
        future.set_result(None)


def check_select(
    key: int | str, include: frozenset[str | int], exclude: frozenset[str | int]
) -> bool:
    if include:
        return key in include and key not in exclude

    return key not in exclude
