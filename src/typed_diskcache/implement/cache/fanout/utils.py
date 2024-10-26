from __future__ import annotations

from copy import copy
from typing import TYPE_CHECKING, Any

from typing_extensions import ParamSpec, TypeAlias, TypeVar

from typed_diskcache import exception as te
from typed_diskcache.log import get_logger

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable, Iterable
    from pathlib import Path

    from _typeshed import StrPath

    from typed_diskcache.database import Connection
    from typed_diskcache.implement.cache.default import Cache
    from typed_diskcache.interface.cache import CacheProtocol
    from typed_diskcache.interface.disk import DiskProtocol
    from typed_diskcache.model import Settings

__all__ = []

_P = ParamSpec("_P")
_C = TypeVar("_C", bound="CacheProtocol")
CleanupFunc: TypeAlias = "Callable[[Iterable[StrPath | None]], None]"
AsyncCleanupFunc: TypeAlias = "Callable[[Iterable[StrPath | None]], Awaitable[Any]]"

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


def update_shards_state(  # noqa: PLR0913
    shards: tuple[Cache, ...],
    directory: Path,
    disk: DiskProtocol,
    conn: Connection,
    settings: Settings,
    page_size: int,
) -> None:
    for index, shard in enumerate(shards):
        update_shard_state(index, shard, directory, disk, conn, settings, page_size)


def update_shard_state(  # noqa: PLR0913
    index: int,
    shard: Cache,
    directory: Path,
    disk: DiskProtocol,
    conn: Connection,
    settings: Settings,
    page_size: int,
) -> None:
    shard._directory = directory / f"{index:03d}"  # noqa: SLF001
    shard._directory.mkdir(parents=True, exist_ok=True)  # noqa: SLF001
    shard._disk = copy(disk)  # noqa: SLF001
    shard._disk.directory = shard.directory  # noqa: SLF001
    shard._conn = conn  # noqa: SLF001
    shard._settings = settings  # noqa: SLF001
    shard._page_size = page_size  # noqa: SLF001
