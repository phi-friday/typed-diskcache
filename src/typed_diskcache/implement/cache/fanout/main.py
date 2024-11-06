from __future__ import annotations

import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from functools import partial
from itertools import chain
from os.path import expandvars
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn, overload

import anyio
from sqlalchemy.exc import OperationalError
from typing_extensions import TypeVar, Unpack, override

from typed_diskcache import exception as te
from typed_diskcache.core.const import DEFAULT_SIZE_LIMIT
from typed_diskcache.core.types import (
    Container,
    FilterMethod,
    FilterMethodLiteral,
    QueueSide,
    QueueSideLiteral,
    SettingsKwargs,
    Stats,
)
from typed_diskcache.exception import TypedDiskcacheError
from typed_diskcache.implement.cache import utils as cache_utils
from typed_diskcache.implement.cache.default import Cache as Shard
from typed_diskcache.implement.cache.fanout import utils as fanout_utils
from typed_diskcache.interface.cache import CacheProtocol

if TYPE_CHECKING:
    from collections.abc import (
        AsyncGenerator,
        AsyncIterator,
        Callable,
        Generator,
        Iterable,
        Iterator,
        Mapping,
    )
    from os import PathLike
    from warnings import WarningMessage

    from typed_diskcache.database import Connection
    from typed_diskcache.interface.disk import DiskProtocol
    from typed_diskcache.model import Settings

__all__ = ["FanoutCache"]

_AnyT = TypeVar("_AnyT", default=Any)


class FanoutCache(CacheProtocol):
    """Disk and file backed cache.

    FanoutCache is a cache that uses multiple shards to store key-value pairs.

    Args:
        directory: directory for cache. Default is `None`.
        disk_type: [`DiskProtocol`][typed_diskcache.interface.disk.DiskProtocol]
            class or callable. Default is `None`.
        disk_args: keyword arguments for `disk_type`. Default is `None`.
        timeout: connection timeout. Default is 60 seconds.
        shard_size: number of shards. Default is 8.
        **kwargs: additional keyword arguments for
            [`Settings`][typed_diskcache.model.Settings].
    """

    __slots__ = ("_shards", "_cache")

    def __init__(
        self,
        directory: str | PathLike[str] | None = None,
        disk_type: type[DiskProtocol] | Callable[..., DiskProtocol] | None = None,
        disk_args: Mapping[str, Any] | None = None,
        timeout: float = 60,
        shard_size: int = 8,
        **kwargs: Unpack[SettingsKwargs],
    ) -> None:
        if directory is None:
            directory = tempfile.mkdtemp(prefix="typed-diskcache-")
        directory = Path(directory)
        directory = cache_utils.ensure_cache_directory(directory)
        directory = directory.expanduser()
        directory = Path(expandvars(directory))

        size_limit = kwargs.get("size_limit", DEFAULT_SIZE_LIMIT)
        kwargs["size_limit"] = size_limit // shard_size

        self._cache = Shard(
            directory,
            disk_type=disk_type,
            disk_args=disk_args,
            timeout=timeout,
            **kwargs,
        )
        constructor = partial(
            Shard, disk_type=disk_type, disk_args=disk_args, timeout=timeout, **kwargs
        )
        with ThreadPoolExecutor(shard_size) as pool:
            futures = pool.map(
                constructor, (directory / f"{index:03d}" for index in range(shard_size))
            )
            self._shards = tuple(futures)

    @override
    def __len__(self) -> int:
        return sum(len(shard) for shard in self._shards)

    @override
    def __setitem__(self, key: Any, value: Any) -> None:
        shard = fanout_utils.get_shard(key, self.disk, self._shards)
        shard[key] = value

    @override
    def __getitem__(self, key: Any) -> Container[Any]:
        shard = fanout_utils.get_shard(key, self.disk, self._shards)
        return shard[key]

    @override
    def __contains__(self, key: Any) -> bool:
        shard = fanout_utils.get_shard(key, self.disk, self._shards)
        return key in shard

    @override
    def __delitem__(self, key: Any) -> None:
        shard = fanout_utils.get_shard(key, self.disk, self._shards)
        del shard[key]

    def __del__(self) -> None:
        with suppress(BaseException):
            self.close()

    @override
    def __iter__(self) -> Iterator[Any]:
        iters = (iter(shard) for shard in self._shards)
        return chain.from_iterable(iters)

    @override
    def __reversed__(self) -> Iterator[Any]:
        iters = (reversed(shard) for shard in reversed(self._shards))
        return chain.from_iterable(iters)

    @override
    def __aiter__(self) -> AsyncIterator[Any]:
        return fanout_utils.aiter_shard(self._shards)

    @override
    def __getstate__(self) -> Mapping[str, Any]:
        import cloudpickle

        return {
            "shards": cloudpickle.dumps(self._shards),
            "cache": cloudpickle.dumps(self._cache),
        }

    @override
    def __setstate__(self, state: Mapping[str, Any]) -> None:
        import cloudpickle

        cache: Shard = cloudpickle.loads(state["cache"])
        shards: tuple[Shard] = cloudpickle.loads(state["shards"])

        self._cache = cache
        self._shards = shards

    @property
    @override
    def directory(self) -> Path:
        return self._cache.directory

    @property
    @override
    def timeout(self) -> float:
        return self._cache.timeout

    @property
    @override
    def conn(self) -> Connection:
        return self._cache.conn

    @property
    @override
    def disk(self) -> DiskProtocol:
        return self._cache.disk

    @property
    @override
    def settings(self) -> Settings:
        return self._cache.settings

    @settings.setter
    def settings(self, value: Settings) -> None:
        self.update_settings(value)

    @overload
    def get(
        self, key: Any, default: _AnyT, *, retry: bool = ...
    ) -> Container[Any | _AnyT]: ...
    @overload
    def get(
        self, key: Any, default: Any = ..., *, retry: bool = ...
    ) -> Container[Any]: ...
    @override
    def get(
        self, key: Any, default: Any = None, *, retry: bool = True
    ) -> Container[Any]:
        shard = fanout_utils.get_shard(key, self.disk, self._shards)
        try:
            return shard.get(key, default=default, retry=retry)
        except (OperationalError, TypedDiskcacheError):
            return cache_utils.wrap_default(default)

    @overload
    async def aget(
        self, key: Any, default: _AnyT, *, retry: bool = ...
    ) -> Container[Any | _AnyT]: ...
    @overload
    async def aget(
        self, key: Any, default: Any = ..., *, retry: bool = ...
    ) -> Container[Any]: ...
    @override
    async def aget(
        self, key: Any, default: Any = None, *, retry: bool = True
    ) -> Container[Any]:
        shard = fanout_utils.get_shard(key, self.disk, self._shards)
        try:
            return await shard.aget(key, default=default, retry=retry)
        except (OperationalError, TypedDiskcacheError):
            return cache_utils.wrap_default(default)

    @override
    def set(
        self,
        key: Any,
        value: Any,
        *,
        expire: float | None = None,
        tags: str | Iterable[str] | None = None,
        retry: bool = False,
    ) -> bool:
        shard = fanout_utils.get_shard(key, self.disk, self._shards)
        try:
            return shard.set(key, value, expire=expire, tags=tags, retry=retry)
        except (OperationalError, TypedDiskcacheError):
            return False

    @override
    async def aset(
        self,
        key: Any,
        value: Any,
        *,
        expire: float | None = None,
        tags: str | Iterable[str] | None = None,
        retry: bool = False,
    ) -> bool:
        shard = fanout_utils.get_shard(key, self.disk, self._shards)
        try:
            return await shard.aset(key, value, expire=expire, tags=tags, retry=retry)
        except (OperationalError, TypedDiskcacheError):
            return False

    @override
    def delete(self, key: Any, *, retry: bool = False) -> bool:
        shard = fanout_utils.get_shard(key, self.disk, self._shards)
        try:
            return shard.delete(key, retry=retry)
        except (OperationalError, TypedDiskcacheError):
            return False

    @override
    async def adelete(self, key: Any, *, retry: bool = False) -> bool:
        shard = fanout_utils.get_shard(key, self.disk, self._shards)
        try:
            return await shard.adelete(key, retry=retry)
        except (OperationalError, TypedDiskcacheError):
            return False

    @override
    def clear(self, *, retry: bool = False) -> int:
        total = 0
        for shard in self._shards:
            total = fanout_utils.loop_total(total, shard.clear, retry=retry)
        return total

    @override
    async def aclear(self, *, retry: bool = False) -> int:
        total = 0
        for shard in self._shards:
            total = await fanout_utils.async_loop_total(
                total, shard.aclear, retry=retry
            )
        return total

    @override
    def volume(self) -> int:
        return sum(shard.volume() for shard in self._shards)

    @override
    async def avolume(self) -> int:
        total = 0
        for shard in self._shards:
            total += await shard.avolume()
        return total

    @override
    def stats(self, *, enable: bool = True, reset: bool = False) -> Stats:
        hits, misses = 0, 0

        for shard in self._shards:
            shard_stats = shard.stats(enable=enable, reset=reset)
            hits += shard_stats[0]
            misses += shard_stats[1]

        self.update_settings(statistics=enable)
        return Stats(hits=hits, misses=misses)

    @override
    async def astats(self, *, enable: bool = True, reset: bool = False) -> Stats:
        hits, misses = 0, 0

        async def update_stats(shard: Shard) -> None:
            nonlocal hits, misses
            shard_stats = await shard.astats(enable=enable, reset=reset)
            hits += shard_stats[0]
            misses += shard_stats[1]

        async with anyio.create_task_group() as task_group:
            for shard in self._shards:
                task_group.start_soon(update_stats, shard)

        await self.aupdate_settings(statistics=enable)
        return Stats(hits=hits, misses=misses)

    @override
    def close(self) -> None:
        self.conn.close()
        for shard in self._shards:
            shard.close()

    @override
    async def aclose(self) -> None:
        await self.conn.aclose()
        async with anyio.create_task_group() as task_group:
            for shard in self._shards:
                task_group.start_soon(shard.aclose)

    @override
    def touch(
        self, key: Any, *, expire: float | None = None, retry: bool = False
    ) -> bool:
        shard = fanout_utils.get_shard(key, self.disk, self._shards)
        try:
            return shard.touch(key, expire=expire, retry=retry)
        except (OperationalError, TypedDiskcacheError):
            return False

    @override
    async def atouch(
        self, key: Any, *, expire: float | None = None, retry: bool = False
    ) -> bool:
        shard = fanout_utils.get_shard(key, self.disk, self._shards)
        try:
            return await shard.atouch(key, expire=expire, retry=retry)
        except (OperationalError, TypedDiskcacheError):
            return False

    @override
    def add(
        self,
        key: Any,
        value: Any,
        *,
        expire: float | None = None,
        tags: str | Iterable[str] | None = None,
        retry: bool = False,
    ) -> bool:
        shard = fanout_utils.get_shard(key, self.disk, self._shards)
        try:
            return shard.add(key, value, expire=expire, tags=tags, retry=retry)
        except (OperationalError, TypedDiskcacheError):
            return False

    @override
    async def aadd(
        self,
        key: Any,
        value: Any,
        *,
        expire: float | None = None,
        tags: str | Iterable[str] | None = None,
        retry: bool = False,
    ) -> bool:
        shard = fanout_utils.get_shard(key, self.disk, self._shards)
        try:
            return await shard.aadd(key, value, expire=expire, tags=tags, retry=retry)
        except (OperationalError, TypedDiskcacheError):
            return False

    @overload
    def pop(
        self, key: Any, default: _AnyT, *, retry: bool = ...
    ) -> Container[Any | _AnyT]: ...
    @overload
    def pop(
        self, key: Any, default: Any = ..., *, retry: bool = ...
    ) -> Container[Any]: ...
    @override
    def pop(
        self, key: Any, default: Any = None, *, retry: bool = True
    ) -> Container[Any]:
        shard = fanout_utils.get_shard(key, self.disk, self._shards)
        try:
            return shard.pop(key, default=default, retry=retry)
        except (OperationalError, TypedDiskcacheError):
            return cache_utils.wrap_default(default)

    @overload
    async def apop(
        self, key: Any, default: _AnyT, *, retry: bool = ...
    ) -> Container[Any | _AnyT]: ...
    @overload
    async def apop(
        self, key: Any, default: Any = ..., *, retry: bool = ...
    ) -> Container[Any]: ...
    @override
    async def apop(
        self, key: Any, default: Any = None, *, retry: bool = True
    ) -> Container[Any]:
        shard = fanout_utils.get_shard(key, self.disk, self._shards)
        try:
            return await shard.apop(key, default=default, retry=retry)
        except (OperationalError, TypedDiskcacheError):
            return cache_utils.wrap_default(default)

    @override
    def filter(
        self,
        tags: str | Iterable[str],
        *,
        method: FilterMethodLiteral | FilterMethod = FilterMethod.OR,
    ) -> Generator[Any, None, None]:
        for shard in self._shards:
            yield from shard.filter(tags, method=method)

    @override
    async def afilter(
        self,
        tags: str | Iterable[str],
        *,
        method: FilterMethodLiteral | FilterMethod = FilterMethod.OR,
    ) -> AsyncGenerator[Any, None]:
        for shard in self._shards:
            async for value in shard.afilter(tags, method=method):
                yield value

    @override
    def incr(
        self, key: Any, delta: int = 1, default: int | None = 0, *, retry: bool = False
    ) -> int:
        shard = fanout_utils.get_shard(key, self.disk, self._shards)
        return shard.incr(key, delta=delta, default=default, retry=retry)

    @override
    async def aincr(
        self, key: Any, delta: int = 1, default: int | None = 0, *, retry: bool = False
    ) -> int:
        shard = fanout_utils.get_shard(key, self.disk, self._shards)
        return await shard.aincr(key, delta=delta, default=default, retry=retry)

    @override
    def decr(
        self, key: Any, delta: int = 1, default: int | None = 0, *, retry: bool = False
    ) -> int:
        shard = fanout_utils.get_shard(key, self.disk, self._shards)
        return shard.decr(key, delta=delta, default=default, retry=retry)

    @override
    async def adecr(
        self, key: Any, delta: int = 1, default: int | None = 0, *, retry: bool = False
    ) -> int:
        shard = fanout_utils.get_shard(key, self.disk, self._shards)
        return await shard.adecr(key, delta=delta, default=default, retry=retry)

    @override
    def evict(
        self,
        tags: str | Iterable[str],
        *,
        method: FilterMethodLiteral | FilterMethod = FilterMethod.OR,
        retry: bool = False,
    ) -> int:
        total = 0
        tags = [tags] if isinstance(tags, str) else tags
        tags = list(tags)

        for shard in self._shards:
            total = fanout_utils.loop_total(
                total, shard.evict, tags, method=method, retry=retry
            )
        return total

    @override
    async def aevict(
        self,
        tags: str | Iterable[str],
        *,
        method: FilterMethodLiteral | FilterMethod = FilterMethod.OR,
        retry: bool = False,
    ) -> int:
        total = 0
        tags = [tags] if isinstance(tags, str) else tags
        tags = list(tags)

        for shard in self._shards:
            total = await fanout_utils.async_loop_total(
                total, shard.aevict, tags, method=method, retry=retry
            )
        return total

    @override
    def expire(self, now: float | None = None, *, retry: bool = False) -> int:
        total = 0
        now = now or time.time()

        for shard in self._shards:
            total = fanout_utils.loop_total(total, shard.expire, now, retry=retry)
        return total

    @override
    async def aexpire(self, now: float | None = None, *, retry: bool = False) -> int:
        total = 0
        now = now or time.time()

        for shard in self._shards:
            total = await fanout_utils.async_loop_total(
                total, shard.aexpire, now, retry=retry
            )
        return total

    @override
    def cull(self, *, retry: bool = False) -> int:
        total = 0

        for shard in self._shards:
            total = fanout_utils.loop_total(total, shard.cull, retry=retry)
        return total

    @override
    async def acull(self, *, retry: bool = False) -> int:
        total = 0

        for shard in self._shards:
            total = await fanout_utils.async_loop_total(total, shard.acull, retry=retry)
        return total

    @override
    def check(self, *, fix: bool = False, retry: bool = False) -> list[WarningMessage]:
        warnings = (shard.check(fix=fix, retry=retry) for shard in self._shards)
        return list(chain.from_iterable(warnings))

    @override
    async def acheck(
        self, *, fix: bool = False, retry: bool = False
    ) -> list[WarningMessage]:
        result: list[WarningMessage] = []
        for shard in self._shards:
            warnings = await shard.acheck(fix=fix, retry=retry)
            result.extend(warnings)
        return result

    @override
    def iterkeys(self, *, reverse: bool = ...) -> Generator[Any, None, None]:
        shards = reversed(self._shards) if reverse else self._shards
        for shard in shards:
            yield from shard.iterkeys(reverse=reverse)

    @override
    async def aiterkeys(self, *, reverse: bool = ...) -> AsyncGenerator[Any, None]:
        shards = reversed(self._shards) if reverse else self._shards
        for shard in shards:
            async for key in shard.aiterkeys(reverse=reverse):
                yield key

    @override
    def push(
        self,
        value: Any,
        *,
        prefix: str | None = None,
        side: QueueSideLiteral | QueueSide = QueueSide.BACK,
        expire: float | None = None,
        tags: str | Iterable[str] | None = None,
        retry: bool = False,
    ) -> NoReturn:
        raise te.TypedDiskcacheNotImplementedError(
            "FanoutCache does not support push operation"
        )

    @override
    async def apush(
        self,
        value: Any,
        *,
        prefix: str | None = None,
        side: QueueSideLiteral | QueueSide = QueueSide.BACK,
        expire: float | None = None,
        tags: str | Iterable[str] | None = None,
        retry: bool = False,
    ) -> NoReturn:
        raise te.TypedDiskcacheNotImplementedError(
            "FanoutCache does not support push operation"
        )

    @override
    def pull(
        self,
        *,
        prefix: str | None = None,
        default: tuple[Any, Any] | None = None,
        side: QueueSideLiteral | QueueSide = QueueSide.FRONT,
        retry: bool = False,
    ) -> NoReturn:
        raise te.TypedDiskcacheNotImplementedError(
            "FanoutCache does not support pull operation"
        )

    @override
    async def apull(
        self,
        *,
        prefix: str | None = None,
        default: tuple[Any, Any] | None = None,
        side: QueueSideLiteral | QueueSide = QueueSide.FRONT,
        retry: bool = False,
    ) -> NoReturn:
        raise te.TypedDiskcacheNotImplementedError(
            "FanoutCache does not support pull operation"
        )

    @override
    def peek(
        self,
        *,
        prefix: str | None = None,
        default: tuple[Any, Any] | None = None,
        side: QueueSideLiteral | QueueSide = QueueSide.BACK,
        retry: bool = False,
    ) -> NoReturn:
        raise te.TypedDiskcacheNotImplementedError(
            "FanoutCache does not support peek operation"
        )

    @override
    async def apeek(
        self,
        *,
        prefix: str | None = None,
        default: tuple[Any, Any] | None = None,
        side: QueueSideLiteral | QueueSide = QueueSide.BACK,
        retry: bool = False,
    ) -> NoReturn:
        raise te.TypedDiskcacheNotImplementedError(
            "FanoutCache does not support peek operation"
        )

    @override
    def peekitem(self, *, last: bool = True, retry: bool = False) -> NoReturn:
        raise te.TypedDiskcacheNotImplementedError(
            "FanoutCache does not support peekitem operation"
        )

    @override
    async def apeekitem(self, *, last: bool = True, retry: bool = False) -> NoReturn:
        raise te.TypedDiskcacheNotImplementedError(
            "FanoutCache does not support peekitem operation"
        )

    @override
    def update_settings(
        self,
        settings: Settings | SettingsKwargs | None = None,
        **kwargs: Unpack[SettingsKwargs],
    ) -> None:
        settings = cache_utils.combine_settings(settings, kwargs)
        for shard in self._shards:
            shard.update_settings(settings)
        self._cache.update_settings(settings)

    @override
    async def aupdate_settings(
        self,
        settings: Settings | SettingsKwargs | None = None,
        **kwargs: Unpack[SettingsKwargs],
    ) -> None:
        settings = cache_utils.combine_settings(settings, kwargs)
        async with anyio.create_task_group() as task_group:
            for shard in self._shards:
                task_group.start_soon(shard.aupdate_settings, settings)
            task_group.start_soon(self._cache.aupdate_settings, settings)
