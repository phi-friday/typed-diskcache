from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeAlias

from typing_extensions import ParamSpec, TypeVar

from typed_diskcache import exception as te
from typed_diskcache.log import get_logger

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable, Iterable
    from os import PathLike

    from typed_diskcache.implement.cache.default import Cache
    from typed_diskcache.interface.cache import CacheProtocol
    from typed_diskcache.interface.disk import DiskProtocol

__all__ = []

_P = ParamSpec("_P")
_C = TypeVar("_C", bound="CacheProtocol")
CleanupFunc: TypeAlias = "Callable[[Iterable[str | PathLike[str] | None]], None]"
AsyncCleanupFunc: TypeAlias = (
    "Callable[[Iterable[str | PathLike[str] | None]], Awaitable[Any]]"
)

logger = get_logger()


def get_shard(key: Any, disk: DiskProtocol, shards: tuple[_C, ...]) -> _C:
    index = disk.hash(key) % len(shards)
    return shards[index]


async def aiter_shard(shards: tuple[Cache, ...]) -> AsyncGenerator[Any, None]:
    for shard in shards:
        async for key in shard:
            yield key


def loop_count(
    total: int, func: Callable[_P, int], *args: _P.args, **kwargs: _P.kwargs
) -> tuple[int, bool]:
    try:
        count = func(*args, **kwargs)
    except te.TypedDiskcacheTimeoutError as exc:
        count = exc.args[0]
    if not count:
        return total, False
    return total + count, True


async def async_loop_count(
    total: int, func: Callable[_P, Awaitable[int]], *args: _P.args, **kwargs: _P.kwargs
) -> tuple[int, bool]:
    try:
        count = await func(*args, **kwargs)
    except te.TypedDiskcacheTimeoutError as exc:
        count = exc.args[0]
    if not count:
        return total, False
    return total + count, True


def loop_total(
    total: int, func: Callable[_P, int], *args: _P.args, **kwargs: _P.kwargs
) -> int:
    flag = True
    while flag:
        total, flag = loop_count(total, func, *args, **kwargs)
    return total


async def async_loop_total(
    total: int, func: Callable[_P, Awaitable[int]], *args: _P.args, **kwargs: _P.kwargs
) -> int:
    flag = True
    while flag:
        total, flag = await async_loop_count(total, func, *args, **kwargs)
    return total
