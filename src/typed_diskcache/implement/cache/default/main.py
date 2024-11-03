from __future__ import annotations

import tempfile
import time
import warnings
from contextlib import suppress
from os.path import expandvars
from pathlib import Path
from typing import TYPE_CHECKING, Any, overload

import sqlalchemy as sa
from sqlalchemy import orm as sa_orm
from typing_extensions import TypeAlias, TypeVar, Unpack, override

from typed_diskcache import exception as te
from typed_diskcache.core.const import ENOVAL
from typed_diskcache.core.context import context, enter_connection
from typed_diskcache.core.types import (
    Container,
    EvictionPolicy,
    FilterMethod,
    FilterMethodLiteral,
    MetadataKey,
    QueueSide,
    QueueSideLiteral,
    SettingsKey,
    SettingsKwargs,
    Stats,
)
from typed_diskcache.database.model import Cache as CacheTable
from typed_diskcache.database.model import Metadata
from typed_diskcache.database.model import Settings as SettingsTable
from typed_diskcache.database.model import Tag as TagTable
from typed_diskcache.exception import TypedDiskcacheTimeoutError
from typed_diskcache.implement.cache import utils as cache_utils
from typed_diskcache.implement.cache.default import utils as default_utils
from typed_diskcache.interface.cache import CacheProtocol
from typed_diskcache.log import get_logger

if TYPE_CHECKING:
    from collections.abc import (
        AsyncGenerator,
        AsyncIterator,
        Awaitable,
        Callable,
        Generator,
        Iterable,
        Iterator,
        Mapping,
    )
    from os import PathLike

    from sqlalchemy.engine import Connection as SAConnection
    from sqlalchemy.ext.asyncio import AsyncConnection

    from typed_diskcache.database import Connection
    from typed_diskcache.interface.disk import DiskProtocol
    from typed_diskcache.model import Settings

__all__ = ["Cache"]

logger = get_logger()
_AnyT = TypeVar("_AnyT", default=Any)
CleanupFunc: TypeAlias = "Callable[[Iterable[str | PathLike[str] | None]], None]"
AsyncCleanupFunc: TypeAlias = (
    "Callable[[Iterable[str | PathLike[str] | None]], Awaitable[Any]]"
)


class Cache(CacheProtocol):
    """Disk and file backed cache.

    Args:
        directory: directory for cache. Default is `None`.
        disk_type: [`DiskProtocol`][typed_diskcache.interface.disk.DiskProtocol]
            class or callable. Default is `None`.
        disk_args: keyword arguments for `disk_type`. Default is `None`.
        timeout: connection timeout. Default is 60 seconds.
        **kwargs: additional keyword arguments for
            [`Settings`][typed_diskcache.model.Settings].
    """

    __slots__ = ("_directory", "_disk", "_conn", "_settings", "_page_size")

    def __init__(
        self,
        directory: str | PathLike[str] | None = None,
        disk_type: type[DiskProtocol] | Callable[..., DiskProtocol] | None = None,
        disk_args: Mapping[str, Any] | None = None,
        timeout: float = 60,
        **kwargs: Unpack[SettingsKwargs],
    ) -> None:
        if directory is None:
            directory = tempfile.mkdtemp(prefix="typed-diskcache-")
        directory = Path(directory).resolve()
        directory = directory.expanduser()
        directory = Path(expandvars(directory))

        disk, conn, settings, page_size = cache_utils.init_args(
            directory, disk_type, disk_args, timeout, **kwargs
        )

        self._directory = directory
        self._disk = disk
        self._conn = conn
        self._settings = settings
        self._page_size = page_size

    @context("Cache.length")
    @override
    def __len__(self) -> int:
        with self.conn.connect() as sa_conn:
            return (
                sa_conn.execute(
                    sa.select(Metadata.value).where(Metadata.key == MetadataKey.COUNT)
                )
                .scalars()
                .one()
            )

    @override
    def __setitem__(self, key: Any, value: Any) -> None:
        self.set(key, value, retry=True)

    @override
    def __getitem__(self, key: Any) -> Container[Any]:
        value = self.get(key, default=ENOVAL, retry=True)
        if value.value is ENOVAL:
            raise te.TypedDiskcacheKeyError(key)
        return value

    @context("Cache.contains")
    @override
    def __contains__(self, key: Any) -> bool:
        db_key, raw = self.disk.put(key)
        with self.conn.connect() as sa_conn:
            row = sa_conn.execute(
                sa.select(CacheTable.id).where(
                    CacheTable.key == db_key,
                    CacheTable.raw == raw,
                    sa.or_(
                        CacheTable.expire_time.is_(None),
                        CacheTable.expire_time > time.time(),
                    ),
                )
            ).one_or_none()

            return row is not None

    @override
    def __delitem__(self, key: Any) -> None:
        result = self.delete(key, retry=False)
        if not result:
            raise te.TypedDiskcacheKeyError(key)

    def __del__(self) -> None:
        with suppress(BaseException):
            self.close()

    @override
    def __iter__(self) -> Iterator[Any]:
        iterator = default_utils.iter_disk(self.conn, self.disk, ascending=True)
        next(iterator)
        return iterator

    @override
    def __reversed__(self) -> Iterator[Any]:
        iterator = default_utils.iter_disk(self.conn, self.disk, ascending=False)
        next(iterator)
        return iterator

    @override
    def __aiter__(self) -> AsyncIterator[Any]:
        return default_utils.aiter_disk(self.conn, self.disk, ascending=True)

    @override
    def __getstate__(self) -> Mapping[str, Any]:
        import cloudpickle

        return {
            "directory": str(self.directory),
            "disk": cloudpickle.dumps(self.disk),
            "conn": cloudpickle.dumps(self.conn),
            "settings": self.settings.model_dump_json(),
            "page_size": self._page_size,
        }

    @override
    def __setstate__(self, state: Mapping[str, Any]) -> None:
        import cloudpickle

        from typed_diskcache.model import Settings

        self._directory = Path(state["directory"])
        self._disk = cloudpickle.loads(state["disk"])
        self._conn = cloudpickle.loads(state["conn"])
        self._settings = Settings.model_validate_json(state["settings"])
        self._page_size = state["page_size"]

    @property
    @override
    def directory(self) -> Path:
        return self._directory

    @property
    @override
    def timeout(self) -> float:
        return self._conn.timeout

    @property
    @override
    def conn(self) -> Connection:
        return self._conn

    @property
    @override
    def disk(self) -> DiskProtocol:
        return self._disk

    @property
    @override
    def settings(self) -> Settings:
        return self._settings

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
    @context
    @override
    def get(
        self, key: Any, default: Any = None, *, retry: bool = True
    ) -> Container[Any]:
        select_stmt = default_utils.prepare_get_stmt(self.disk, key)

        if (
            not self.settings.statistics
            and self.settings.eviction_policy == EvictionPolicy.NONE
        ):
            logger.debug("Cache statistics disabled or eviction policy is NONE")
            with self.conn.connect() as sa_conn:
                row = sa_conn.execute(
                    select_stmt, {"expire_time": time.time()}
                ).one_or_none()

                if row is None:
                    logger.debug("Key `%s` not found", key)
                    return cache_utils.wrap_default(default)

                try:
                    value = self.disk.fetch(
                        mode=row.mode, filename=row.filepath, value=row.value
                    )
                except OSError:
                    logger.debug("Key `%s` file `%s` not found", key, row.filepath)
                    return cache_utils.wrap_default(default)

                logger.debug("Key `%s` found", key)
                return cache_utils.wrap_instnace(key, value, row, sa_conn)

        cache_hit_stmt, cache_miss_stmt, update_stmt = (
            default_utils.prepare_get_update_stmt(self.conn)
        )

        with default_utils.transact(conn=self.conn, disk=self.disk, retry=retry) as (
            sa_conn,
            _,
        ):
            row = sa_conn.execute(
                select_stmt, {"expire_time": time.time()}
            ).one_or_none()

            if row is None:
                logger.debug("Key `%s` not found", key)
                if self.settings.statistics:
                    logger.debug("Update cache miss statistics")
                    sa_conn.execute(cache_miss_stmt)
                return cache_utils.wrap_default(default)

            try:
                value = self.disk.fetch(
                    mode=row.mode, filename=row.filepath, value=row.value
                )
            except OSError:
                logger.debug("Key `%s` file `%s` not found", key, row.filepath)
                if self.settings.statistics:
                    logger.debug("Update cache miss statistics")
                    sa_conn.execute(cache_miss_stmt)
                return cache_utils.wrap_default(default)

            if self.settings.statistics:
                logger.debug("Update cache hit statistics")
                sa_conn.execute(cache_hit_stmt)
            if update_stmt is not None:
                logger.debug("Update eviction metadata")
                sa_conn.execute(
                    update_stmt,
                    {
                        "id": row.id,
                        "access_time": time.time(),
                        "access_count": row.access_count + 1,
                    },
                )

            logger.debug("Key `%s` found", key)
            return cache_utils.wrap_instnace(key, value, row, sa_conn)

    @overload
    async def aget(
        self, key: Any, default: _AnyT, *, retry: bool = ...
    ) -> Container[Any | _AnyT]: ...
    @overload
    async def aget(
        self, key: Any, default: Any = ..., *, retry: bool = ...
    ) -> Container[Any]: ...
    @context
    @override
    async def aget(
        self, key: Any, default: Any = None, *, retry: bool = True
    ) -> Container[Any]:
        select_stmt = default_utils.prepare_get_stmt(self.disk, key)

        if (
            not self.settings.statistics
            and self.settings.eviction_policy == EvictionPolicy.NONE
        ):
            logger.debug("Cache statistics disabled or eviction policy is NONE")
            async with self.conn.aconnect() as sa_conn:
                row_fetch = await sa_conn.execute(
                    select_stmt.options(sa_orm.joinedload(CacheTable.tags)),
                    {"expire_time": time.time()},
                )
                row = row_fetch.first()

                if row is None:
                    logger.debug("Key `%s` not found", key)
                    return cache_utils.wrap_default(default)

                try:
                    value = await self.disk.afetch(
                        mode=row.mode, filename=row.filepath, value=row.value
                    )
                except OSError:
                    logger.debug("Key `%s` file `%s` not found", key, row.filepath)
                    return cache_utils.wrap_default(default)

                logger.debug("Key `%s` found", key)
                return await cache_utils.async_wrap_instnace(key, value, row, sa_conn)

        cache_hit_stmt, cache_miss_stmt, update_stmt = (
            default_utils.prepare_get_update_stmt(self.conn)
        )

        async with default_utils.async_transact(
            conn=self.conn, disk=self.disk, retry=retry
        ) as (sa_conn, _):
            row_fetch = await sa_conn.execute(
                select_stmt.options(sa_orm.joinedload(CacheTable.tags)),
                {"expire_time": time.time()},
            )
            row = row_fetch.first()

            if row is None:
                logger.debug("Key `%s` not found", key)
                if self.settings.statistics:
                    logger.debug("Update cache miss statistics")
                    await sa_conn.execute(cache_miss_stmt)
                return cache_utils.wrap_default(default)

            try:
                value = await self.disk.afetch(
                    mode=row.mode, filename=row.filepath, value=row.value
                )
            except OSError:
                logger.debug("Key `%s` file `%s` not found", key, row.filepath)
                if self.settings.statistics:
                    logger.debug("Update cache miss statistics")
                    await sa_conn.execute(cache_miss_stmt)
                return cache_utils.wrap_default(default)

            if self.settings.statistics:
                logger.debug("Update cache hit statistics")
                await sa_conn.execute(cache_hit_stmt)
            if update_stmt is not None:
                logger.debug("Update eviction metadata")
                await sa_conn.execute(
                    update_stmt,
                    {
                        "id": row.id,
                        "access_time": time.time(),
                        "access_count": row.access_count + 1,
                    },
                )

            logger.debug("Key `%s` found", key)
            return await cache_utils.async_wrap_instnace(key, value, row, sa_conn)

    @context
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
        instance, instance_tags, full_path = default_utils.create_cache_instance(
            disk=self.disk, key=key, value=value, expire=expire, tags=tags
        )

        with default_utils.transact(
            conn=self.conn, disk=self.disk, retry=retry, filename=instance.filepath
        ) as (sa_conn, cleanup):
            row = sa_conn.execute(
                sa.select(CacheTable).where(
                    CacheTable.key == instance.key, CacheTable.raw == instance.raw
                )
            ).one_or_none()

            if row is not None:
                if row.filepath:
                    logger.debug("Cleanup file `%s`", row.filepath)
                    cleanup([row.filepath])
                logger.debug("Update key `%s`", key)
                instance.id = row.id
            instance = default_utils.build_cache_instance(
                instance=instance,
                disk=self.disk,
                value=value,
                key=key,
                filepath=(instance.filepath, full_path),
                instance_tags=instance_tags,
            )
            default_utils.merge_cache(instance, instance_tags, sa_conn)
            self._cull(instance.access_time, sa_conn, cleanup)

            return True
        return False

    @context
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
        instance, instance_tags, full_path = default_utils.create_cache_instance(
            disk=self.disk, key=key, value=value, expire=expire, tags=tags
        )

        async with default_utils.async_transact(
            conn=self.conn, disk=self.disk, retry=retry, filename=instance.filepath
        ) as (sa_conn, cleanup):
            row_fetch = await sa_conn.execute(
                sa.select(CacheTable).where(
                    CacheTable.key == instance.key, CacheTable.raw == instance.raw
                )
            )
            row = row_fetch.one_or_none()

            if row is not None:
                if row.filepath:
                    logger.debug("Cleanup file `%s`", row.filepath)
                    await cleanup([row.filepath])
                logger.debug("Update key `%s`", key)
                instance.id = row.id
            instance = await default_utils.async_build_cache_instance(
                instance=instance,
                disk=self.disk,
                value=value,
                key=key,
                filepath=(instance.filepath, full_path),
                instance_tags=instance_tags,
            )
            await default_utils.async_merge_cache(instance, instance_tags, sa_conn)
            await self._async_cull(instance.access_time, sa_conn, cleanup)

            return True
        return False

    @context
    @override
    def delete(self, key: Any, *, retry: bool = False) -> bool:
        stmt = default_utils.prepare_delete_stmt(self.disk, key)
        with default_utils.transact(conn=self.conn, disk=self.disk, retry=retry) as (
            sa_conn,
            cleanup,
        ):
            row = sa_conn.execute(stmt).one_or_none()

            if row is None:
                logger.debug("Key `%s` not found", key)
                return False

            logger.debug("Delete key `%s`", key)
            sa_conn.execute(sa.delete(CacheTable).where(CacheTable.id == row.id))
            cleanup([row.filepath])
            return True
        return False

    @context
    @override
    async def adelete(self, key: Any, *, retry: bool = False) -> bool:
        stmt = default_utils.prepare_delete_stmt(self.disk, key)
        async with default_utils.async_transact(
            conn=self.conn, disk=self.disk, retry=retry
        ) as (sa_conn, cleanup):
            row_fetch = await sa_conn.execute(stmt)
            row = row_fetch.one_or_none()

            if row is None:
                logger.debug("Key `%s` not found", key)
                return False

            logger.debug("Delete key `%s`", key)
            await sa_conn.execute(sa.delete(CacheTable).where(CacheTable.id == row.id))
            await cleanup([row.filepath])
            return True
        return False

    @context
    @override
    def clear(self, *, retry: bool = False) -> int:
        stmt = default_utils.prepare_clear_args()
        return default_utils.select_delete(
            conn=self.conn,
            disk=self.disk,
            select_stmt=stmt,
            params={"id": 0, "limit": 100},
            params_key_mapping=("id", "id"),
            retry=retry,
        )

    @context
    @override
    async def aclear(self, *, retry: bool = False) -> int:
        stmt = default_utils.prepare_clear_args()
        return await default_utils.async_select_delete(
            conn=self.conn,
            disk=self.disk,
            select_stmt=stmt,
            params={"id": 0, "limit": 100},
            params_key_mapping=("id", "id"),
            retry=retry,
        )

    def _cull(
        self,
        now: float,
        connection: SAConnection,
        cleanup: CleanupFunc,
        limit: int | None = None,
        stacklevel: int = 2,
    ) -> None:
        cull_limit = self.settings.cull_limit if limit is None else limit
        if cull_limit <= 0:
            logger.debug(
                "Culling limit %d is less than or equal to 0",
                cull_limit,
                stacklevel=stacklevel,
            )
            return

        filenames_select_stmt, filenames_delete_stmt, select_stmt = (
            default_utils.prepare_cull_stmt(self.conn, now=now, cull_limit=cull_limit)
        )

        filenames = connection.execute(filenames_select_stmt).scalars().all()
        if filenames:
            logger.debug(
                "Culling cleanup files: %d", len(filenames), stacklevel=stacklevel
            )
            connection.execute(filenames_delete_stmt)
            cleanup(filenames)

            cull_limit -= len(filenames)
            logger.debug("Culling limit: %d", cull_limit, stacklevel=stacklevel)

            if cull_limit <= 0:
                return

        if select_stmt is None or self.volume() < self.settings.size_limit:
            logger.debug(
                "Volume is less than size limit %d",
                self.settings.size_limit,
                stacklevel=stacklevel,
            )
            return

        rows = connection.execute(select_stmt, {"limit": cull_limit}).all()

        if rows:
            logger.debug("Culling cleanup files: %d", len(rows), stacklevel=stacklevel)
            connection.execute(
                sa.delete(CacheTable).where(
                    CacheTable.id.in_(
                        select_stmt.with_only_columns(CacheTable.id).scalar_subquery()
                    )
                ),
                {"limit": cull_limit},
            )
            cleanup([row.filepath for row in rows])

    async def _async_cull(
        self,
        now: float,
        connection: AsyncConnection,
        cleanup: AsyncCleanupFunc,
        limit: int | None = None,
        stacklevel: int = 2,
    ) -> None:
        cull_limit = self.settings.cull_limit if limit is None else limit
        if cull_limit <= 0:
            logger.debug(
                "Culling limit %d is less than or equal to 0",
                cull_limit,
                stacklevel=stacklevel,
            )
            return

        filenames_select_stmt, filenames_delete_stmt, select_stmt = (
            default_utils.prepare_cull_stmt(self.conn, now=now, cull_limit=cull_limit)
        )

        filenames_fetch = await connection.execute(filenames_select_stmt)
        filenames = filenames_fetch.scalars().all()
        if filenames:
            logger.debug(
                "Culling cleanup files: %d", len(filenames), stacklevel=stacklevel
            )
            await connection.execute(filenames_delete_stmt)
            await cleanup(filenames)

            cull_limit -= len(filenames)
            logger.debug("Culling limit: %d", cull_limit, stacklevel=stacklevel)

            if cull_limit <= 0:
                return

        if select_stmt is None or await self.avolume() < self.settings.size_limit:
            logger.debug(
                "Volume is less than size limit %d",
                self.settings.size_limit,
                stacklevel=stacklevel,
            )
            return

        rows_fetch = await connection.execute(select_stmt, {"limit": cull_limit})
        rows = rows_fetch.all()

        if rows:
            logger.debug("Culling cleanup files: %d", len(rows), stacklevel=stacklevel)
            await connection.execute(
                sa.delete(CacheTable).where(
                    CacheTable.id.in_(
                        select_stmt.with_only_columns(CacheTable.id).scalar_subquery()
                    )
                ),
                {"limit": cull_limit},
            )
            logger.debug("Culling cleanup files: %d", len(rows), stacklevel=stacklevel)
            await cleanup([row.filepath for row in rows])

    @context
    @override
    def volume(self) -> int:
        with self.conn.connect() as sa_conn:
            page_count: int = sa_conn.execute(
                sa.text("PRAGMA page_count;")
            ).scalar_one()
            size: int = sa_conn.execute(
                sa.select(Metadata.value).where(Metadata.key == MetadataKey.SIZE)
            ).scalar_one()

        return self._page_size * page_count + size

    @context
    @override
    async def avolume(self) -> int:
        async with self.conn.aconnect() as sa_conn:
            page_count_fetch = await sa_conn.execute(sa.text("PRAGMA page_count;"))
            size_fetch = await sa_conn.execute(
                sa.select(Metadata.value).where(Metadata.key == MetadataKey.SIZE)
            )
            page_count: int = page_count_fetch.scalar_one()
            size: int = size_fetch.scalar_one()

        return self._page_size * page_count + size

    @context
    @override
    def stats(self, *, enable: bool = True, reset: bool = False) -> Stats:
        with default_utils.transact(conn=self.conn, disk=self.disk, retry=False) as (
            sa_conn,
            _,
        ):
            hits = (
                sa_conn.execute(
                    sa.select(Metadata.value).where(Metadata.key == MetadataKey.HITS)
                )
                .scalars()
                .one()
            )
            misses = (
                sa_conn.execute(
                    sa.select(Metadata.value).where(Metadata.key == MetadataKey.MISSES)
                )
                .scalars()
                .one()
            )
            stats = Stats(hits=hits, misses=misses)

            if reset:
                sa_conn.execute(
                    sa.update(Metadata)
                    .values(value=0)
                    .where(Metadata.key.in_([MetadataKey.HITS, MetadataKey.MISSES]))
                )

            sa_conn.execute(
                sa.update(SettingsTable)
                .where(SettingsTable.key == SettingsKey.STATISTICS)
                .values(value=enable)
            )
            with enter_connection(sa_conn) as context:
                context.run(
                    self.update_settings,
                    self.settings.model_copy(update={"statistics": enable}),
                )

            return stats

    @context
    @override
    async def astats(self, *, enable: bool = True, reset: bool = False) -> Stats:
        async with default_utils.async_transact(
            conn=self.conn, disk=self.disk, retry=False
        ) as (sa_conn, _):
            hits_fetch = await sa_conn.execute(
                sa.select(Metadata.value).where(Metadata.key == MetadataKey.HITS)
            )
            misses_fetch = await sa_conn.execute(
                sa.select(Metadata.value).where(Metadata.key == MetadataKey.MISSES)
            )
            hits = hits_fetch.scalars().one()
            misses = misses_fetch.scalars().one()
            stats = Stats(hits=hits, misses=misses)

            if reset:
                await sa_conn.execute(
                    sa.update(Metadata)
                    .values(value=0)
                    .where(Metadata.key.in_([MetadataKey.HITS, MetadataKey.MISSES]))
                )

            await sa_conn.execute(
                sa.update(SettingsTable)
                .where(SettingsTable.key == SettingsKey.STATISTICS)
                .values(value=enable)
            )
            with enter_connection(sa_conn) as context:
                await context.run(
                    self.aupdate_settings,
                    self.settings.model_copy(update={"statistics": enable}),
                )
            return stats

    @override
    def close(self) -> None:
        self.conn.close()

    @override
    async def aclose(self) -> None:
        await self.conn.aclose()

    @context
    @override
    def touch(
        self, key: Any, *, expire: float | None = None, retry: bool = False
    ) -> bool:
        now = time.time()
        db_key, raw = self.disk.put(key)
        expire_time = None if expire is None else now + expire

        with default_utils.transact(conn=self.conn, disk=self.disk, retry=retry) as (
            sa_conn,
            _,
        ):
            row = sa_conn.execute(
                sa.select(CacheTable).where(
                    CacheTable.key == db_key, CacheTable.raw == raw
                )
            ).one_or_none()

            if row is None:
                logger.debug("Key `%s` not found", key)
                return False

            if row.expire_time is None or row.expire_time > now:
                logger.debug("Touch key `%s`", key)
                sa_conn.execute(
                    sa.update(CacheTable)
                    .where(CacheTable.id == row.id)
                    .values(expire_time=expire_time)
                )
                return True

        return False

    @context
    @override
    async def atouch(
        self, key: Any, *, expire: float | None = None, retry: bool = False
    ) -> bool:
        now = time.time()
        db_key, raw = self.disk.put(key)
        expire_time = None if expire is None else now + expire

        async with default_utils.async_transact(
            conn=self.conn, disk=self.disk, retry=retry
        ) as (sa_conn, _):
            row_fetch = await sa_conn.execute(
                sa.select(CacheTable).where(
                    CacheTable.key == db_key, CacheTable.raw == raw
                )
            )
            row = row_fetch.one_or_none()

            if row is None:
                logger.debug("Key `%s` not found", key)
                return False

            if row.expire_time is None or row.expire_time > now:
                logger.debug("Touch key `%s`", key)
                await sa_conn.execute(
                    sa.update(CacheTable)
                    .where(CacheTable.id == row.id)
                    .values(expire_time=expire_time)
                )
                return True

        return False

    @context
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
        instance, instance_tags, full_path = default_utils.create_cache_instance(
            disk=self.disk, key=key, value=value, expire=expire, tags=tags
        )

        with default_utils.transact(
            conn=self.conn, disk=self.disk, retry=retry, filename=instance.filepath
        ) as (sa_conn, cleanup):
            row = sa_conn.execute(
                sa.select(CacheTable).where(
                    CacheTable.key == instance.key, CacheTable.raw == instance.raw
                )
            ).one_or_none()

            if row is not None:
                logger.debug("Key `%s` already exists", key)

                if row.expire_time is None or row.expire_time > instance.access_time:
                    cleanup([instance.filepath])
                    return False

            if row is not None:
                if row.filepath:
                    logger.debug("Cleanup file `%s`", row.filepath)
                    cleanup([row.filepath])
                logger.debug("Update key `%s`", key)
                instance.id = row.id
            instance = default_utils.build_cache_instance(
                instance=instance,
                disk=self.disk,
                value=value,
                key=key,
                filepath=(instance.filepath, full_path),
                instance_tags=instance_tags,
            )
            default_utils.merge_cache(instance, instance_tags, sa_conn)
            self._cull(instance.access_time, sa_conn, cleanup)

            return True

    @context
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
        instance, instance_tags, full_path = default_utils.create_cache_instance(
            disk=self.disk, key=key, value=value, expire=expire, tags=tags
        )

        async with default_utils.async_transact(
            conn=self.conn, disk=self.disk, retry=retry, filename=instance.filepath
        ) as (sa_conn, cleanup):
            row_fetch = await sa_conn.execute(
                sa.select(CacheTable).where(
                    CacheTable.key == instance.key, CacheTable.raw == instance.raw
                )
            )
            row = row_fetch.one_or_none()

            if row is not None:
                logger.debug("Key `%s` already exists", key)

                if row.expire_time is None or row.expire_time > instance.access_time:
                    await cleanup([instance.filepath])
                    return False

            if row is not None:
                if row.filepath:
                    logger.debug("Cleanup file `%s`", row.filepath)
                    await cleanup([row.filepath])
                logger.debug("Update key `%s`", key)
                instance.id = row.id
            instance = default_utils.build_cache_instance(
                instance=instance,
                disk=self.disk,
                value=value,
                key=key,
                filepath=(instance.filepath, full_path),
                instance_tags=instance_tags,
            )
            await default_utils.async_merge_cache(instance, instance_tags, sa_conn)
            await self._async_cull(instance.access_time, sa_conn, cleanup)

            return True

    @overload
    def pop(
        self, key: Any, default: _AnyT, *, retry: bool = ...
    ) -> Container[Any | _AnyT]: ...
    @overload
    def pop(
        self, key: Any, default: Any = ..., *, retry: bool = ...
    ) -> Container[Any]: ...
    @context
    @override
    def pop(
        self, key: Any, default: Any = None, *, retry: bool = True
    ) -> Container[Any]:
        select_stmt = default_utils.prepare_get_stmt(self.disk, key)
        with default_utils.transact(conn=self.conn, disk=self.disk, retry=retry) as (
            sa_conn,
            _,
        ):
            row = sa_conn.execute(
                select_stmt, {"expire_time": time.time()}
            ).one_or_none()

            if row is None:
                logger.debug("Key `%s` not found", key)
                return cache_utils.wrap_default(default)

            sa_conn.execute(sa.delete(CacheTable).where(CacheTable.id == row.id))

            try:
                value = self.disk.fetch(
                    mode=row.mode, filename=row.filepath, value=row.value
                )
            except OSError:
                logger.debug("Key `%s` file `%s` not found", key, row.filepath)
                return cache_utils.wrap_default(default)
            finally:
                if row.filepath:
                    logger.debug("Cleanup file `%s`", row.filepath)
                    self.disk.remove(row.filepath)

            logger.debug("Key `%s` found", key)
            return cache_utils.wrap_instnace(key, value, row, sa_conn)

    @overload
    async def apop(
        self, key: Any, default: _AnyT, *, retry: bool = ...
    ) -> Container[Any | _AnyT]: ...
    @overload
    async def apop(
        self, key: Any, default: Any = ..., *, retry: bool = ...
    ) -> Container[Any]: ...
    @context
    @override
    async def apop(
        self, key: Any, default: Any = None, *, retry: bool = True
    ) -> Container[Any]:
        select_stmt = default_utils.prepare_get_stmt(self.disk, key)
        async with default_utils.async_transact(
            conn=self.conn, disk=self.disk, retry=retry
        ) as (sa_conn, _):
            row_fetch = await sa_conn.execute(
                select_stmt.options(sa_orm.joinedload(CacheTable.tags)),
                {"expire_time": time.time()},
            )
            row = row_fetch.first()

            if row is None:
                logger.debug("Key `%s` not found", key)
                return cache_utils.wrap_default(default)

            await sa_conn.execute(sa.delete(CacheTable).where(CacheTable.id == row.id))

            try:
                value = await self.disk.afetch(
                    mode=row.mode, filename=row.filepath, value=row.value
                )
            except OSError:
                logger.debug("Key `%s` file `%s` not found", key, row.filepath)
                return cache_utils.wrap_default(default)
            finally:
                if row.filepath:
                    logger.debug("Cleanup file `%s`", row.filepath)
                    await self.disk.aremove(row.filepath)

            logger.debug("Key `%s` found", key)
            return await cache_utils.async_wrap_instnace(key, value, row, sa_conn)

    @context
    @override
    def filter(
        self,
        tags: str | Iterable[str],
        *,
        method: FilterMethodLiteral | FilterMethod = FilterMethod.OR,
    ) -> Generator[Any, None, None]:
        max_id = default_utils.find_max_id(self.conn)
        if max_id is None:
            return

        stmt = default_utils.prepare_filter_stmt(method=method)
        tags = [tags] if isinstance(tags, str) else tags
        tags = list(tags)

        lower_bound = 0
        tags_count = len(tags)
        while True:
            with self.conn.connect() as sa_conn:
                rows = sa_conn.execute(
                    stmt,
                    {
                        "lower_bound": lower_bound,
                        "tags_list": tags,
                        "tags_count": tags_count,
                        "chunksize": 100,
                    },
                ).all()

                if not rows:
                    break

                for row in rows:
                    yield self.disk.get(row.key, raw=row.raw)
                lower_bound = rows[-1].id

    @context
    @override
    async def afilter(
        self,
        tags: str | Iterable[str],
        *,
        method: FilterMethodLiteral | FilterMethod = FilterMethod.OR,
    ) -> AsyncGenerator[Any, None]:
        max_id = await default_utils.async_find_max_id(self.conn)
        if max_id is None:
            return

        stmt = default_utils.prepare_filter_stmt(method=method)
        tags = [tags] if isinstance(tags, str) else tags
        tags = list(tags)

        lower_bound = 0
        tags_count = len(tags)
        while True:
            async with self.conn.aconnect() as sa_conn:
                rows_fetch = await sa_conn.execute(
                    stmt,
                    {
                        "lower_bound": lower_bound,
                        "tags_list": tags,
                        "tags_count": tags_count,
                        "chunksize": 100,
                    },
                )
                rows = rows_fetch.all()

                if not rows:
                    break

                for row in rows:
                    yield self.disk.get(row.key, raw=row.raw)
                lower_bound = rows[-1].id

    @context
    @override
    def incr(
        self, key: Any, delta: int = 1, default: int | None = 0, *, retry: bool = False
    ) -> int:
        now = time.time()
        db_key, raw = self.disk.put(key)

        with default_utils.transact(conn=self.conn, disk=self.disk, retry=retry) as (
            sa_conn,
            cleanup,
        ):
            row = sa_conn.execute(
                sa.select(CacheTable).where(
                    CacheTable.key == db_key, CacheTable.raw == raw
                )
            ).one_or_none()

            if row is None:
                if default is None:
                    logger.debug("Key `%s` not found", key)
                    raise te.TypedDiskcacheKeyError(key)

                logger.debug("Key `%s` not found, use default `%d`", key, default)
                value = default + delta

                instance, instance_tags, full_path = (
                    default_utils.create_cache_instance(
                        disk=self.disk, key=key, value=value, expire=None, tags=None
                    )
                )
                instance = default_utils.build_cache_instance(
                    instance=instance,
                    disk=self.disk,
                    value=value,
                    key=key,
                    filepath=(instance.filepath, full_path),
                    instance_tags=instance_tags,
                )
                default_utils.merge_cache(instance, instance_tags, sa_conn)
                self._cull(instance.access_time, sa_conn, cleanup)
                return value

            if row.expire_time is not None and row.expire_time < now:
                if default is None:
                    logger.debug("Key `%s` expired", key)
                    raise te.TypedDiskcacheKeyError(key)

                logger.debug("Key `%s` not found, use default `%d`", key, default)
                value = default + delta

                instance, instance_tags, full_path = (
                    default_utils.create_cache_instance(
                        disk=self.disk, key=key, value=value, expire=None, tags=None
                    )
                )
                if row.filepath:
                    logger.debug("Cleanup file `%s`", row.filepath)
                    cleanup([row.filepath])
                logger.debug("Update key `%s`", key)
                instance.id = row.id
                instance = default_utils.build_cache_instance(
                    instance=instance,
                    disk=self.disk,
                    value=value,
                    key=key,
                    filepath=(instance.filepath, full_path),
                    instance_tags=instance_tags,
                )
                default_utils.merge_cache(instance, instance_tags, sa_conn)
                self._cull(instance.access_time, sa_conn, cleanup)
                return value

            value = self.disk.fetch(
                mode=row.mode, filename=row.filepath, value=row.value
            )
            value += delta
            origin_filepath = row.filepath
            row.size, row.mode, row.filepath, row.value = self.disk.store(
                value, key=row.key
            )
            update_stmt = self.conn.eviction.get
            if update_stmt is not None:
                logger.debug("Update eviction metadata")
                sa_conn.execute(
                    update_stmt,
                    {
                        "id": row.id,
                        "access_time": now,
                        "access_count": row.access_count + 1,
                    },
                )

            row.store_time = now
            default_utils.merge_cache(row, set(), sa_conn)
            if origin_filepath:
                cleanup([origin_filepath])

            return value

    @context
    @override
    async def aincr(
        self, key: Any, delta: int = 1, default: int | None = 0, *, retry: bool = False
    ) -> int:
        now = time.time()
        db_key, raw = self.disk.put(key)

        async with default_utils.async_transact(
            conn=self.conn, disk=self.disk, retry=retry
        ) as (sa_conn, cleanup):
            row_fetch = await sa_conn.execute(
                sa.select(CacheTable).where(
                    CacheTable.key == db_key, CacheTable.raw == raw
                )
            )
            row = row_fetch.one_or_none()

            if row is None:
                if default is None:
                    logger.debug("Key `%s` not found", key)
                    raise te.TypedDiskcacheKeyError(key)

                logger.debug("Key `%s` not found, use default `%d`", key, default)
                value = default + delta

                instance, instance_tags, full_path = (
                    default_utils.create_cache_instance(
                        disk=self.disk, key=key, value=value, expire=None, tags=None
                    )
                )
                instance = await default_utils.async_build_cache_instance(
                    instance=instance,
                    disk=self.disk,
                    value=value,
                    key=key,
                    filepath=(instance.filepath, full_path),
                    instance_tags=instance_tags,
                )
                await default_utils.async_merge_cache(instance, instance_tags, sa_conn)
                await self._async_cull(instance.access_time, sa_conn, cleanup)
                return value

            if row.expire_time is not None and row.expire_time < now:
                if default is None:
                    logger.debug("Key `%s` expired", key)
                    raise te.TypedDiskcacheKeyError(key)

                logger.debug("Key `%s` not found, use default `%d`", key, default)
                value = default + delta

                instance, instance_tags, full_path = (
                    default_utils.create_cache_instance(
                        disk=self.disk, key=key, value=value, expire=None, tags=None
                    )
                )
                if row.filepath:
                    logger.debug("Cleanup file `%s`", row.filepath)
                    await cleanup([row.filepath])
                logger.debug("Update key `%s`", key)
                instance.id = row.id
                instance = await default_utils.async_build_cache_instance(
                    instance=instance,
                    disk=self.disk,
                    value=value,
                    key=key,
                    filepath=(instance.filepath, full_path),
                    instance_tags=instance_tags,
                )
                await default_utils.async_merge_cache(instance, instance_tags, sa_conn)
                await self._async_cull(instance.access_time, sa_conn, cleanup)
                return value

            value = await self.disk.afetch(
                mode=row.mode, filename=row.filepath, value=row.value
            )
            value += delta
            origin_filepath = row.filepath
            row.size, row.mode, row.filepath, row.value = await self.disk.astore(
                value, key=row.key
            )
            update_stmt = self.conn.eviction.get
            if update_stmt is not None:
                logger.debug("Update eviction metadata")
                await sa_conn.execute(
                    update_stmt,
                    {
                        "id": row.id,
                        "access_time": now,
                        "access_count": row.access_count + 1,
                    },
                )

            row.store_time = now
            await default_utils.async_merge_cache(row, set(), sa_conn)
            if origin_filepath:
                await cleanup([origin_filepath])

            return value

    @context
    @override
    def decr(
        self, key: Any, delta: int = 1, default: int | None = 0, *, retry: bool = False
    ) -> int:
        return self.incr(key, -delta, default, retry=retry)

    @context
    @override
    async def adecr(
        self, key: Any, delta: int = 1, default: int | None = 0, *, retry: bool = False
    ) -> int:
        return await self.aincr(key, -delta, default, retry=retry)

    @context
    @override
    def evict(
        self,
        tags: str | Iterable[str],
        *,
        method: FilterMethodLiteral | FilterMethod = FilterMethod.OR,
        retry: bool = False,
    ) -> int:
        stmt = default_utils.prepare_evict_stmt(method=method)
        tags = [tags] if isinstance(tags, str) else tags
        tags = list(tags)

        return default_utils.select_delete(
            conn=self.conn,
            disk=self.disk,
            select_stmt=stmt,
            params={"lower_bound": 0, "select_tags": tags, "tags_count": len(tags)},
            params_key_mapping=("lower_bound", "id"),
            retry=retry,
        )

    @context
    @override
    async def aevict(
        self,
        tags: str | Iterable[str],
        *,
        method: FilterMethodLiteral | FilterMethod = FilterMethod.OR,
        retry: bool = False,
    ) -> int:
        stmt = default_utils.prepare_evict_stmt(method=method)
        tags = [tags] if isinstance(tags, str) else tags
        tags = list(tags)

        return await default_utils.async_select_delete(
            conn=self.conn,
            disk=self.disk,
            select_stmt=stmt,
            params={"lower_bound": 0, "select_tags": tags, "tags_count": len(tags)},
            params_key_mapping=("lower_bound", "id"),
            retry=retry,
        )

    @context
    @override
    def expire(self, now: float | None = None, *, retry: bool = False) -> int:
        stmt = default_utils.prepare_expire_stmt()
        return default_utils.select_delete(
            conn=self.conn,
            disk=self.disk,
            select_stmt=stmt,
            params={"expire_time": now or time.time()},
            params_key_mapping=("expire_time", "expire_time"),
            retry=retry,
        )

    @context
    @override
    async def aexpire(self, now: float | None = None, *, retry: bool = False) -> int:
        stmt = default_utils.prepare_expire_stmt()
        return await default_utils.async_select_delete(
            conn=self.conn,
            disk=self.disk,
            select_stmt=stmt,
            params={"expire_time": now or time.time()},
            params_key_mapping=("expire_time", "expire_time"),
            retry=retry,
        )

    @context
    @override
    def cull(self, *, retry: bool = False) -> int:
        now = time.time()

        # Remove expired items.

        count = self.expire(now)

        # Remove items by policy.

        select_policy = self.conn.eviction.cull
        if select_policy is None:
            logger.debug("No cull policy")
            return 0

        select_stmt = select_policy.with_only_columns(CacheTable.filepath)
        delete_stmt = sa.delete(CacheTable).where(
            CacheTable.id.in_(
                select_policy.with_only_columns(CacheTable.id).scalar_subquery()
            )
        )
        try:
            while self.volume() > self.settings.size_limit:
                with default_utils.transact(
                    conn=self.conn, disk=self.disk, retry=retry
                ) as (sa_conn, cleanup):
                    rows = sa_conn.execute(select_stmt, {"limit": 10}).scalars().all()

                    if not rows:
                        logger.debug("No more items to cull")
                        break

                    count += len(rows)
                    sa_conn.execute(delete_stmt, {"limit": 10})

                    cleanup(rows)
        except TimeoutError as exc:
            raise TypedDiskcacheTimeoutError(count) from exc

        return count

    @context
    @override
    async def acull(self, *, retry: bool = False) -> int:
        now = time.time()

        # Remove expired items.

        count = await self.aexpire(now)

        # Remove items by policy.

        select_policy = self.conn.eviction.cull
        if select_policy is None:
            logger.debug("No cull policy")
            return 0

        select_stmt = select_policy.with_only_columns(CacheTable.filepath)
        delete_stmt = sa.delete(CacheTable).where(
            CacheTable.id.in_(
                select_policy.with_only_columns(CacheTable.id).scalar_subquery()
            )
        )
        try:
            while await self.avolume() > self.settings.size_limit:
                async with default_utils.async_transact(
                    conn=self.conn, disk=self.disk, retry=retry
                ) as (sa_conn, cleanup):
                    rows_fetch = await sa_conn.execute(select_stmt, {"limit": 10})
                    rows = rows_fetch.scalars().all()

                    if not rows:
                        logger.debug("No more items to cull")
                        break

                    count += len(rows)
                    await sa_conn.execute(delete_stmt, {"limit": 10})

                    await cleanup(rows)
        except TimeoutError as exc:
            raise TypedDiskcacheTimeoutError(count) from exc

        return count

    @context
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
    ) -> Any:
        stmt, now, expire_time, tags = default_utils.prepare_push_args(
            prefix=prefix, side=side, expire=expire, tags=tags
        )
        size, mode, filename, db_value = self.disk.store(value)

        with default_utils.transact(
            conn=self.conn, disk=self.disk, retry=retry, filename=filename
        ) as (sa_conn, cleanup):
            db_key = sa_conn.scalars(stmt).one_or_none()
            cache_key = default_utils.find_push_key(
                prefix=prefix, db_key=db_key, side=side
            )
            db_key = str(cache_key).encode()

            instance = CacheTable(
                key=db_key,
                raw=True,
                store_time=now,
                access_time=now,
                value=db_value,
                filepath=filename,
                expire_time=expire_time,
                mode=mode,
                size=size,
                access_count=0,
            )
            instance_tags = {TagTable(name=tag) for tag in (tags or [])}
            default_utils.merge_cache(instance, instance_tags, sa_conn)
            self._cull(now, sa_conn, cleanup)

            return cache_key

    @context
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
    ) -> Any:
        stmt, now, expire_time, tags = default_utils.prepare_push_args(
            prefix=prefix, side=side, expire=expire, tags=tags
        )
        size, mode, filename, db_value = await self.disk.astore(value)

        async with default_utils.async_transact(
            conn=self.conn, disk=self.disk, retry=retry, filename=filename
        ) as (sa_conn, cleanup):
            db_key_fetch = await sa_conn.scalars(stmt)
            db_key = db_key_fetch.one_or_none()
            cache_key = default_utils.find_push_key(
                prefix=prefix, db_key=db_key, side=side
            )
            db_key = str(cache_key).encode()

            instance = CacheTable(
                key=db_key,
                raw=True,
                store_time=now,
                access_time=now,
                value=db_value,
                filepath=filename,
                expire_time=expire_time,
                mode=mode,
                size=size,
                access_count=0,
            )
            instance_tags = {TagTable(name=tag) for tag in (tags or [])}
            await default_utils.async_merge_cache(instance, instance_tags, sa_conn)
            await self._async_cull(now, sa_conn, cleanup)

            return cache_key

    @overload
    def pull(
        self,
        *,
        prefix: str | None = ...,
        default: None,
        side: QueueSideLiteral | QueueSide = ...,
        retry: bool = ...,
    ) -> Container[Any | None]: ...
    @overload
    def pull(
        self,
        *,
        prefix: str | None = ...,
        default: tuple[Any, _AnyT],
        side: QueueSideLiteral | QueueSide = ...,
        retry: bool = ...,
    ) -> Container[Any | _AnyT]: ...
    @overload
    def pull(
        self,
        *,
        prefix: str | None = ...,
        default: tuple[Any, Any],
        side: QueueSideLiteral | QueueSide = ...,
        retry: bool = ...,
    ) -> Container[Any]: ...
    @overload
    def pull(
        self,
        *,
        prefix: str | None = ...,
        default: tuple[Any, Any] | None = ...,
        side: QueueSideLiteral | QueueSide = ...,
        retry: bool = ...,
    ) -> Container[Any]: ...
    @context
    @override
    def pull(  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        *,
        prefix: str | None = None,
        default: tuple[Any, Any] | None = None,
        side: QueueSideLiteral | QueueSide = QueueSide.FRONT,
        retry: bool = False,
    ) -> Container[Any]:
        stmt = default_utils.prepare_pull_or_peek_stmt(prefix=prefix, side=side)
        while True:
            rows = default_utils.pull_process(
                conn=self.conn, disk=self.disk, stmt=stmt, default=default, retry=retry
            )
            if isinstance(rows, Container):
                return rows
            if rows is None:
                continue
            break

        row, value, tags = rows
        key = row.key.decode() if prefix else int(row.key)
        return cache_utils.wrap_instnace(key, value, row, tags)

    @overload
    async def apull(
        self,
        *,
        prefix: str | None = ...,
        default: None,
        side: QueueSideLiteral | QueueSide = ...,
        retry: bool = ...,
    ) -> Container[Any | None]: ...
    @overload
    async def apull(
        self,
        *,
        prefix: str | None = ...,
        default: tuple[Any, _AnyT],
        side: QueueSideLiteral | QueueSide = ...,
        retry: bool = ...,
    ) -> Container[Any | _AnyT]: ...
    @overload
    async def apull(
        self,
        *,
        prefix: str | None = ...,
        default: tuple[Any, Any],
        side: QueueSideLiteral | QueueSide = ...,
        retry: bool = ...,
    ) -> Container[Any]: ...
    @overload
    async def apull(
        self,
        *,
        prefix: str | None = ...,
        default: tuple[Any, Any] | None = ...,
        side: QueueSideLiteral | QueueSide = ...,
        retry: bool = ...,
    ) -> Container[Any]: ...
    @context
    @override
    async def apull(  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        *,
        prefix: str | None = None,
        default: tuple[Any, Any] | None = None,
        side: QueueSideLiteral | QueueSide = QueueSide.FRONT,
        retry: bool = False,
    ) -> Container[Any]:
        stmt = default_utils.prepare_pull_or_peek_stmt(prefix=prefix, side=side)
        while True:
            rows = await default_utils.apull_process(
                conn=self.conn, disk=self.disk, stmt=stmt, default=default, retry=retry
            )
            if isinstance(rows, Container):
                return rows
            if rows is None:
                continue
            break

        row, value, tags = rows
        key = row.key.decode() if prefix else int(row.key)
        return await cache_utils.async_wrap_instnace(key, value, row, tags)

    @overload
    def peek(
        self,
        *,
        prefix: str | None = ...,
        default: None,
        side: QueueSideLiteral | QueueSide = ...,
        retry: bool = ...,
    ) -> Container[Any | None]: ...
    @overload
    def peek(
        self,
        *,
        prefix: str | None = ...,
        default: tuple[Any, _AnyT],
        side: QueueSideLiteral | QueueSide = ...,
        retry: bool = ...,
    ) -> Container[Any | _AnyT]: ...
    @overload
    def peek(
        self,
        *,
        prefix: str | None = ...,
        default: tuple[Any, Any],
        side: QueueSideLiteral | QueueSide = ...,
        retry: bool = ...,
    ) -> Container[Any]: ...
    @overload
    def peek(
        self,
        *,
        prefix: str | None = ...,
        default: tuple[Any, Any] | None = ...,
        side: QueueSideLiteral | QueueSide = ...,
        retry: bool = ...,
    ) -> Container[Any]: ...
    @context
    @override
    def peek(  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        *,
        prefix: str | None = None,
        default: tuple[Any, Any] | None = None,
        side: QueueSideLiteral | QueueSide = QueueSide.BACK,
        retry: bool = False,
    ) -> Container[Any]:
        stmt = default_utils.prepare_pull_or_peek_stmt(prefix=prefix, side=side)
        while True:
            rows = default_utils.peek_process(
                conn=self.conn, disk=self.disk, stmt=stmt, default=default, retry=retry
            )
            if isinstance(rows, Container):
                return rows
            if rows is None:
                continue
            break

        row, value, tags = rows
        key = row.key.decode() if prefix else int(row.key)
        return cache_utils.wrap_instnace(key, value, row, tags)

    @overload
    async def apeek(
        self,
        *,
        prefix: str | None = ...,
        default: None,
        side: QueueSideLiteral | QueueSide = ...,
        retry: bool = ...,
    ) -> Container[Any | None]: ...
    @overload
    async def apeek(
        self,
        *,
        prefix: str | None = ...,
        default: tuple[Any, _AnyT],
        side: QueueSideLiteral | QueueSide = ...,
        retry: bool = ...,
    ) -> Container[Any | _AnyT]: ...
    @overload
    async def apeek(
        self,
        *,
        prefix: str | None = ...,
        default: tuple[Any, Any],
        side: QueueSideLiteral | QueueSide = ...,
        retry: bool = ...,
    ) -> Container[Any]: ...
    @overload
    async def apeek(
        self,
        *,
        prefix: str | None = ...,
        default: tuple[Any, Any] | None = ...,
        side: QueueSideLiteral | QueueSide = ...,
        retry: bool = ...,
    ) -> Container[Any]: ...
    @context
    @override
    async def apeek(  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        *,
        prefix: str | None = None,
        default: tuple[Any, Any] | None = None,
        side: QueueSideLiteral | QueueSide = QueueSide.BACK,
        retry: bool = False,
    ) -> Container[Any]:
        stmt = default_utils.prepare_pull_or_peek_stmt(prefix=prefix, side=side)
        while True:
            rows = await default_utils.apeek_process(
                conn=self.conn, disk=self.disk, stmt=stmt, default=default, retry=retry
            )
            if isinstance(rows, Container):
                return rows
            if rows is None:
                continue
            break

        row, value, tags = rows
        key = row.key.decode() if prefix else int(row.key)
        return await cache_utils.async_wrap_instnace(key, value, row, tags)

    @context
    @override
    def peekitem(self, *, last: bool = True, retry: bool = False) -> Container[Any]:
        stmt = default_utils.peekitem_stmt(last=last)
        while True:
            rows = default_utils.peekitem_process(
                conn=self.conn, disk=self.disk, stmt=stmt, retry=retry
            )
            if rows is None:
                continue
            break

        row, value, tags = rows
        key = self.disk.get(row.key, raw=row.raw)
        return cache_utils.wrap_instnace(key, value, row, tags)

    @context
    @override
    async def apeekitem(
        self, *, last: bool = True, retry: bool = False
    ) -> Container[Any]:
        stmt = default_utils.peekitem_stmt(last=last)
        while True:
            rows = await default_utils.apeekitem_process(
                conn=self.conn, disk=self.disk, stmt=stmt, retry=retry
            )
            if rows is None:
                continue
            break

        row, value, tags = rows
        key = self.disk.get(row.key, raw=row.raw)
        return await cache_utils.async_wrap_instnace(key, value, row, tags)

    @context
    @override
    def check(
        self, *, fix: bool = False, retry: bool = False
    ) -> list[warnings.WarningMessage]:
        with warnings.catch_warnings(record=True) as warns:
            default_utils.check_integrity(conn=self.conn, fix=fix, stacklevel=2)
            with default_utils.transact(
                conn=self.conn, disk=self.disk, retry=retry
            ) as (sa_conn, _):
                default_utils.check_files(
                    connection=sa_conn, directory=self.directory, fix=fix, stacklevel=2
                )
                default_utils.check_metadata_count(
                    connection=sa_conn, fix=fix, stacklevel=2
                )
                default_utils.check_metadata_size(
                    connection=sa_conn, fix=fix, stacklevel=2
                )

        return warns

    @context
    @override
    async def acheck(
        self, *, fix: bool = False, retry: bool = False
    ) -> list[warnings.WarningMessage]:
        with warnings.catch_warnings(record=True) as warns:
            await default_utils.acheck_integrity(conn=self.conn, fix=fix, stacklevel=2)

            async with default_utils.async_transact(
                conn=self.conn, disk=self.disk, retry=retry
            ) as (sa_conn, _):
                await default_utils.acheck_files(
                    connection=sa_conn, directory=self.directory, fix=fix, stacklevel=2
                )
                await default_utils.acheck_metadata_count(
                    connection=sa_conn, fix=fix, stacklevel=2
                )
                await default_utils.acheck_metadata_size(
                    connection=sa_conn, fix=fix, stacklevel=2
                )

        return warns

    @context
    @override
    def iterkeys(self, *, reverse: bool = False) -> Generator[Any, None, None]:
        select_stmt, iter_stmt = default_utils.prepare_iterkeys_stmt(reverse=reverse)
        with self.conn.connect() as sa_conn:
            row = sa_conn.execute(select_stmt).one_or_none()

            if not row:
                return

            yield self.disk.get(row.key, raw=row.raw)

            while True:
                rows = sa_conn.execute(
                    iter_stmt,
                    {"iter_key": row.key, "iter_raw": row.raw, "chunksize": 100},
                ).all()

                if not rows:
                    break

                for row in rows:
                    yield self.disk.get(row.key, raw=row.raw)

    @context
    @override
    async def aiterkeys(self, *, reverse: bool = False) -> AsyncGenerator[Any, None]:
        select_stmt, iter_stmt = default_utils.prepare_iterkeys_stmt(reverse=reverse)
        async with self.conn.aconnect() as sa_conn:
            row_fetch = await sa_conn.execute(select_stmt)
            row = row_fetch.one_or_none()

            if not row:
                return

            yield self.disk.get(row.key, raw=row.raw)

            while True:
                rows_fetch = await sa_conn.execute(
                    iter_stmt,
                    {"iter_key": row.key, "iter_raw": row.raw, "chunksize": 100},
                )
                rows = rows_fetch.all()

                if not rows:
                    break

                for row in rows:
                    yield self.disk.get(row.key, raw=row.raw)

    @context
    @override
    def update_settings(
        self,
        settings: Settings | SettingsKwargs | None = None,
        **kwargs: Unpack[SettingsKwargs],
    ) -> None:
        settings = cache_utils.combine_settings(settings, kwargs)
        update_args = default_utils.prepare_update_settings_args(
            self.settings, settings
        )
        if not isinstance(update_args, tuple):
            self._settings = settings
            self.conn.update_settings(settings)
            return

        settings, update_settings, update_stmt = update_args
        with default_utils.transact(conn=self.conn, disk=self.disk, retry=True) as (
            sa_conn,
            _,
        ):
            for key, value in update_settings.items():
                logger.debug("Update setting `%s` to `%s`", key, value)
                sa_conn.execute(
                    update_stmt, {"settings_key": key, "settings_value": value}
                )

        self._settings = settings
        self.conn.update_settings(settings)

    @context
    @override
    async def aupdate_settings(
        self,
        settings: Settings | SettingsKwargs | None = None,
        **kwargs: Unpack[SettingsKwargs],
    ) -> None:
        settings = cache_utils.combine_settings(settings, kwargs)
        update_args = default_utils.prepare_update_settings_args(
            self.settings, settings
        )
        if not isinstance(update_args, tuple):
            self._settings = settings
            self.conn.update_settings(settings)
            return

        settings, update_settings, update_stmt = update_args
        async with default_utils.async_transact(
            conn=self.conn, disk=self.disk, retry=True
        ) as (sa_conn, _):
            for key, value in update_settings.items():
                logger.debug("Update setting `%s` to `%s`", key, value)
                await sa_conn.execute(
                    update_stmt, {"settings_key": key, "settings_value": value}
                )

        self._settings = settings
        self.conn.update_settings(settings)
