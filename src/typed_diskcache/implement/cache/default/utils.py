from __future__ import annotations

import os
import time
import warnings
from contextlib import AsyncExitStack, ExitStack, asynccontextmanager, contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import sqlalchemy as sa
from sqlalchemy.exc import OperationalError
from typing_extensions import TypeAlias, TypeVar, Unpack

from typed_diskcache import exception as te
from typed_diskcache.core.const import (
    DBNAME,
    QUEUE_KEY_DEFAULT,
    QUEUE_KEY_MAXIMA,
    QUEUE_KEY_MINIMA,
)
from typed_diskcache.core.types import (
    CacheMode,
    Container,
    FilterMethod,
    MetadataKey,
    QueueSide,
    QueueSideLiteral,
)
from typed_diskcache.database.connect import transact as database_transact
from typed_diskcache.database.model import Cache as CacheTable
from typed_diskcache.database.model import CacheTag as CacheTagTable
from typed_diskcache.database.model import Metadata
from typed_diskcache.database.model import Settings as SettingsTable
from typed_diskcache.database.model import Tag as TagTable
from typed_diskcache.log import get_logger

if TYPE_CHECKING:
    from collections.abc import (
        AsyncGenerator,
        Awaitable,
        Callable,
        Generator,
        Iterable,
        Mapping,
    )
    from os import PathLike

    from anyio import Path as AnyioPath
    from anyio.streams.memory import MemoryObjectSendStream
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import Session

    from typed_diskcache.database import Connection
    from typed_diskcache.interface.disk import DiskProtocol
    from typed_diskcache.model import Settings

__all__ = []

_T = TypeVar("_T", infer_variance=True)
CleanupFunc: TypeAlias = "Callable[[Iterable[str | PathLike[str] | None]], None]"
AsyncCleanupFunc: TypeAlias = (
    "Callable[[Iterable[str | PathLike[str] | None]], Awaitable[Any]]"
)

logger = get_logger()


def prepare_get_stmt(disk: DiskProtocol, key: Any) -> sa.Select[tuple[CacheTable]]:
    db_key, raw = disk.put(key)
    return (
        sa.select(CacheTable)
        .select_from(CacheTable)
        .where(
            CacheTable.key == db_key,
            CacheTable.raw == raw,
            sa.or_(
                CacheTable.expire_time.is_(None),
                CacheTable.expire_time > sa.bindparam("expire_time", type_=sa.Float()),
            ),
        )
    )


def prepare_get_update_stmt(
    conn: Connection,
) -> tuple[sa.Update, sa.Update, sa.Update | None]:
    cache_hit_stmt = (
        sa.update(Metadata)
        .values(value=Metadata.value + 1)
        .where(Metadata.key == MetadataKey.HITS)
    )
    cache_miss_stmt = (
        sa.update(Metadata)
        .values(value=Metadata.value + 1)
        .where(Metadata.key == MetadataKey.MISSES)
    )
    update_stmt = conn.eviction.get
    return cache_hit_stmt, cache_miss_stmt, update_stmt


def prepare_delete_stmt(disk: DiskProtocol, key: Any) -> sa.Select[tuple[CacheTable]]:
    db_key, raw = disk.put(key)
    return sa.select(CacheTable).where(
        CacheTable.key == db_key,
        CacheTable.raw == raw,
        sa.or_(CacheTable.expire_time.is_(None), CacheTable.expire_time > time.time()),
    )


def prepare_clear_args() -> sa.Select[tuple[int, str | None]]:
    return (
        sa.select(CacheTable.id, CacheTable.filepath)
        .where(CacheTable.id > sa.bindparam("id", type_=sa.Integer()))
        .order_by(CacheTable.id)
        .limit(sa.bindparam("limit", type_=sa.Integer()))
    )


def prepare_clear_stmt() -> tuple[list[int], sa.Delete]:
    count_container = [0]
    delete_stmt = sa.delete(CacheTable).where(
        CacheTable.id.in_(sa.bindparam("ids", expanding=True, type_=sa.Integer()))
    )
    return count_container, delete_stmt


def prepare_cull_stmt(
    conn: Connection, now: float, cull_limit: int
) -> tuple[
    sa.Select[tuple[str | None]], sa.Delete, sa.Select[tuple[CacheTable]] | None
]:
    filenames_select_stmt = (
        sa.select(CacheTable.filepath)
        .where(CacheTable.expire_time.is_not(None), CacheTable.expire_time < now)
        .order_by(CacheTable.expire_time)
        .limit(cull_limit)
    )
    filenames_delete_stmt = sa.delete(CacheTable).where(
        CacheTable.id.in_(
            sa.select(CacheTable.id)
            .where(CacheTable.expire_time.is_not(None), CacheTable.expire_time < now)
            .order_by(CacheTable.expire_time)
            .limit(cull_limit)
            .scalar_subquery()
        )
    )
    select_stmt = conn.eviction.cull

    return filenames_select_stmt, filenames_delete_stmt, select_stmt


def transact_process(
    stack: ExitStack,
    conn: Connection,
    disk: DiskProtocol,
    *,
    retry: bool = False,
    filename: str | PathLike[str] | None = None,
) -> Session | None:
    try:
        session = stack.enter_context(conn.sync_session)
        session = stack.enter_context(database_transact(session))
    except OperationalError as exc:
        stack.close()
        if not retry:
            if filename is not None:
                disk.remove(filename)
            raise te.TypedDiskcacheTimeoutError from exc
        return None
    else:
        return session


async def async_transact_process(
    stack: AsyncExitStack,
    conn: Connection,
    disk: DiskProtocol,
    *,
    retry: bool = False,
    filename: str | PathLike[str] | None = None,
) -> AsyncSession | None:
    try:
        session = await stack.enter_async_context(conn.async_session)
        session = await stack.enter_async_context(database_transact(session))
    except OperationalError as exc:
        await stack.aclose()
        if not retry:
            if filename is not None:
                await disk.aremove(filename)
            raise te.TypedDiskcacheTimeoutError from exc
        return None
    else:
        return session


def iter_disk(
    conn: Connection, disk: DiskProtocol, *, ascending: bool = True
) -> Generator[Any, None, None]:
    max_id = find_max_id(conn)
    yield
    if max_id is None:
        return

    bound = max_id + 1
    limit = 100
    rowid = 0 if ascending else bound
    stmt = (
        sa.select(CacheTable.id, CacheTable.key, CacheTable.raw)
        .where(
            CacheTable.id > sa.bindparam("left_bound", type_=sa.Integer()),
            CacheTable.id < sa.bindparam("right_bound", type_=sa.Integer()),
        )
        .order_by(CacheTable.id.asc() if ascending else CacheTable.id.desc())
        .limit(limit)
    )

    while True:
        with conn.sync_session as session:
            rows = session.execute(
                stmt, {"left_bound": rowid, "right_bound": bound}
            ).all()
            if not rows:
                break

            for row in rows:
                yield disk.get(row[1], raw=row[2])
            rowid = rows[-1][0]


async def aiter_disk(
    conn: Connection, disk: DiskProtocol, *, ascending: bool = True
) -> AsyncGenerator[Any, None]:
    max_id = await async_find_max_id(conn)
    if max_id is None:
        return

    bound = max_id + 1
    limit = 100
    rowid = 0 if ascending else bound
    stmt = (
        sa.select(CacheTable.id, CacheTable.key, CacheTable.raw)
        .where(
            CacheTable.id > sa.bindparam("left_bound", type_=sa.Integer()),
            CacheTable.id < sa.bindparam("right_bound", type_=sa.Integer()),
        )
        .order_by(CacheTable.id.asc() if ascending else CacheTable.id.desc())
        .limit(limit)
    )

    while True:
        async with conn.async_session as session:
            rows_fetch = await session.execute(
                stmt, {"left_bound": rowid, "right_bound": bound}
            )
            rows = rows_fetch.all()
            if not rows:
                break

            for row in rows:
                yield disk.get(row[1], raw=row[2])
            rowid = rows[-1][0]


def extend_queue(
    stream: MemoryObjectSendStream[_T],
) -> Callable[[Iterable[_T]], Awaitable[Any]]:
    import anyio

    async def extend(items: Iterable[_T]) -> None:
        logger.debug("Stream stats: %r", stream.statistics())
        with stream.clone() as clone:
            async with anyio.create_task_group() as task_group:
                for item in items:
                    task_group.start_soon(clone.send, item)

    return extend


def load_tags(tags: set[TagTable], session: Session) -> None:
    db_tags = session.scalars(
        sa.select(TagTable).where(TagTable.name.in_([x.name for x in tags]))
    ).all()
    if not db_tags:
        return

    db_tags_map = {x.name: x for x in db_tags}
    for tag in tags:
        if tag.name not in db_tags_map:
            continue
        tag.id = db_tags_map[tag.name].id


async def async_load_tags(tags: set[TagTable], session: AsyncSession) -> None:
    db_tags = await session.scalars(
        sa.select(TagTable).where(TagTable.name.in_([x.name for x in tags]))
    )
    if not db_tags:
        return

    db_tags_map = {x.name: x for x in db_tags}
    for tag in tags:
        if tag.name not in db_tags_map:
            continue
        tag.id = db_tags_map[tag.name].id


def select_delete(  # noqa: PLR0913
    *,
    conn: Connection,
    disk: DiskProtocol,
    select_stmt: sa.Select[tuple[int, str | None, Unpack[tuple[Any, ...]]]],
    params: Mapping[str, Any],
    params_key_mapping: tuple[str, str],
    retry: bool,
    stacklevel: int = 2,
) -> int:
    count_container, delete_stmt = prepare_clear_stmt()
    try:
        select_delete_process(
            conn=conn,
            disk=disk,
            select_stmt=select_stmt,
            delete_stmt=delete_stmt,
            params=dict(params),
            params_key_mapping=params_key_mapping,
            retry=retry,
            count_container=count_container,
            stacklevel=stacklevel + 1,
        )
    except te.TypedDiskcacheTimeoutError as exc:
        raise te.TypedDiskcacheTimeoutError(count_container[0]) from exc

    return count_container[0]


async def async_select_delete(  # noqa: PLR0913
    *,
    conn: Connection,
    disk: DiskProtocol,
    select_stmt: sa.Select[tuple[int, str | None, Unpack[tuple[Any, ...]]]],
    params: Mapping[str, Any],
    params_key_mapping: tuple[str, str],
    retry: bool,
    stacklevel: int = 2,
) -> int:
    count_container, delete_stmt = prepare_clear_stmt()
    try:
        await async_select_delete_process(
            conn=conn,
            disk=disk,
            select_stmt=select_stmt,
            delete_stmt=delete_stmt,
            params=dict(params),
            params_key_mapping=params_key_mapping,
            retry=retry,
            count_container=count_container,
            stacklevel=stacklevel + 1,
        )
    except te.TypedDiskcacheTimeoutError as exc:
        raise te.TypedDiskcacheTimeoutError(count_container[0]) from exc

    return count_container[0]


def select_delete_process(  # noqa: PLR0913
    *,
    conn: Connection,
    disk: DiskProtocol,
    select_stmt: sa.Select[tuple[int, str | None, Unpack[tuple[Any, ...]]]],
    delete_stmt: sa.Delete,
    params: dict[str, Any],
    params_key_mapping: tuple[str, str],
    retry: bool,
    count_container: list[int],
    stacklevel: int = 2,
) -> None:
    while True:
        with transact(conn=conn, disk=disk, retry=retry) as (session, cleanup):
            logger.debug(
                "Selecting rows with params: %s", params, stacklevel=stacklevel
            )
            rows = session.execute(select_stmt, params).all()
            if not rows:
                logger.debug(
                    "No more rows to delete, params: %s", params, stacklevel=stacklevel
                )
                break
            logger.debug("Deleting rows: %d", len(rows), stacklevel=stacklevel)
            count_container[0] += len(rows)
            session.execute(delete_stmt, {"ids": [row[0] for row in rows]})

            cleanup([row[1] for row in rows])
            params[params_key_mapping[0]] = rows[-1]._mapping[params_key_mapping[1]]  # noqa: SLF001


async def async_select_delete_process(  # noqa: PLR0913
    *,
    conn: Connection,
    disk: DiskProtocol,
    select_stmt: sa.Select[tuple[int, str | None, Unpack[tuple[Any, ...]]]],
    delete_stmt: sa.Delete,
    params: dict[str, Any],
    params_key_mapping: tuple[str, str],
    retry: bool,
    count_container: list[int],
    stacklevel: int = 2,
) -> None:
    while True:
        async with async_transact(conn=conn, disk=disk, retry=retry) as (
            session,
            cleanup,
        ):
            logger.debug(
                "Selecting rows with params: %s", params, stacklevel=stacklevel
            )
            rows_fetch = await session.execute(select_stmt, params)
            rows = rows_fetch.all()
            if not rows:
                logger.debug(
                    "No more rows to delete, params: %s", params, stacklevel=stacklevel
                )
                break

            logger.debug("Deleting rows: %d", len(rows), stacklevel=stacklevel)
            count_container[0] += len(rows)
            await session.execute(delete_stmt, {"ids": [row[0] for row in rows]})

            await cleanup([row[1] for row in rows])
            params[params_key_mapping[0]] = rows[-1]._mapping[params_key_mapping[1]]  # noqa: SLF001


@contextmanager
def transact(
    *,
    conn: Connection,
    disk: DiskProtocol,
    retry: bool = False,
    filename: str | PathLike[str] | None = None,
    stacklevel: int = 3,
) -> Generator[tuple[Session, CleanupFunc], None, None]:
    filenames: list[str | PathLike[str] | None] = []
    with ExitStack() as stack:
        session: Session | None = None
        while session is None:
            stack.close()
            session = transact_process(
                stack, conn, disk, retry=retry, filename=filename
            )

        logger.debug("Enter transaction `%s`", filename, stacklevel=stacklevel)
        stack.callback(
            logger.debug, "Exit transaction `%s`", filename, stacklevel=stacklevel + 2
        )
        try:
            yield session, filenames.extend
        except BaseException:
            session.rollback()
            raise
        else:
            session.commit()
            for name in filenames:
                if name is not None:
                    logger.debug("Cleanup `%s`", name, stacklevel=stacklevel)
                    disk.remove(name)


@asynccontextmanager
async def async_transact(
    *,
    conn: Connection,
    disk: DiskProtocol,
    retry: bool = False,
    filename: str | PathLike[str] | None = None,
    stacklevel: int = 3,
) -> AsyncGenerator[tuple[AsyncSession, AsyncCleanupFunc], None]:
    import anyio

    send, receive = anyio.create_memory_object_stream["str | PathLike[str] | None"](
        1_000_000
    )
    async with AsyncExitStack() as stack:
        session: AsyncSession | None = None
        while session is None:
            await stack.aclose()
            session = await async_transact_process(
                stack, conn, disk, retry=retry, filename=filename
            )

        logger.debug("Enter async transaction `%s`", filename, stacklevel=stacklevel)
        stack.callback(
            logger.debug, "Exit async transaction `%s`", filename, stacklevel=stacklevel
        )
        try:
            stack.enter_context(receive)
            with send:
                yield session, extend_queue(send)
        except BaseException:
            await session.rollback()
            raise
        else:
            await session.commit()
            async for name in receive:
                if name is not None:
                    logger.debug("Cleanup `%s`", name, stacklevel=stacklevel)
                    await disk.aremove(name)


def create_cache_instance(
    disk: DiskProtocol,
    key: Any,
    value: Any,
    *,
    expire: float | None = None,
    tags: str | Iterable[str] | None = None,
) -> tuple[CacheTable, set[TagTable], Path | None]:
    now = time.time()
    db_key, raw = disk.put(key)
    expire_time = None if expire is None else now + expire
    filename, full_path = disk.prepare(value, key=key) or (None, None)
    if isinstance(tags, str):
        tags = [tags]
    if tags is not None:
        tags = set(tags)

    instance = CacheTable(
        key=db_key,
        raw=raw,
        store_time=now,
        expire_time=expire_time,
        access_time=now,
        access_count=0,
        size=0,
        mode=CacheMode.NONE,
        filepath=filename,
        value=None,
    )

    instance_tags = {TagTable(name=x) for x in tags or []}

    return instance, instance_tags, full_path


def build_cache_instance(  # noqa: PLR0913
    *,
    instance: CacheTable,
    disk: DiskProtocol,
    value: Any,
    key: Any,
    filepath: tuple[str | PathLike[str] | None, str | PathLike[str] | None] | None,
    instance_tags: set[TagTable],
) -> CacheTable:
    instance.tags = instance_tags
    if filepath is None or filepath[0] is None or filepath[1] is None:
        instance.size, instance.mode, instance.filepath, instance.value = disk.store(
            value, key=key
        )
    else:
        instance.size, instance.mode, instance.filepath, instance.value = disk.store(
            value,
            key=key,
            filepath=filepath,  # pyright: ignore[reportArgumentType]
        )
    return instance


async def async_build_cache_instance(  # noqa: PLR0913
    *,
    instance: CacheTable,
    disk: DiskProtocol,
    value: Any,
    key: Any,
    filepath: tuple[str | PathLike[str] | None, str | PathLike[str] | None] | None,
    instance_tags: set[TagTable],
) -> CacheTable:
    instance.tags = instance_tags
    if filepath is None or filepath[0] is None or filepath[1] is None:
        (
            instance.size,
            instance.mode,
            instance.filepath,
            instance.value,
        ) = await disk.astore(value, key=key)
    else:
        (
            instance.size,
            instance.mode,
            instance.filepath,
            instance.value,
        ) = await disk.astore(
            value,
            key=key,
            filepath=filepath,  # pyright: ignore[reportArgumentType]
        )
    return instance


def prepare_filter_stmt(
    *, method: Literal["and", "or"] | FilterMethod
) -> sa.Select[tuple[int, bytes, bool]]:
    method = FilterMethod(method)
    stmt = (
        sa.select(CacheTable.id.distinct().label("id"), CacheTable.key, CacheTable.raw)
        .select_from(
            sa.join(
                CacheTable,
                CacheTagTable,
                CacheTable.id == CacheTagTable.cache_id,
                isouter=False,
            ).join(TagTable, CacheTagTable.tag_id == TagTable.id, isouter=False)
        )
        .where(
            CacheTable.id > sa.bindparam("lower_bound", type_=sa.Integer()),
            TagTable.name.in_(
                sa.bindparam("tags_list", type_=sa.String(), expanding=True)
            ),
            sa.or_(
                CacheTable.expire_time.is_(None), CacheTable.expire_time > time.time()
            ),
        )
        .order_by(CacheTable.id.asc())
        .limit(sa.bindparam("chunksize", type_=sa.Integer()))
    )

    if method == FilterMethod.AND:
        stmt = stmt.group_by(CacheTable.id).having(
            sa.func.count(TagTable.id) == sa.bindparam("tags_count", type_=sa.Integer())
        )

    return stmt


def find_max_id(conn: Connection) -> int | None:
    with conn.sync_session as session:
        return session.scalar(sa.select(sa.func.max(CacheTable.id)))


async def async_find_max_id(conn: Connection) -> int | None:
    async with conn.async_session as session:
        return await session.scalar(sa.select(sa.func.max(CacheTable.id)))


def prepare_evict_stmt(
    method: Literal["and", "or"] | FilterMethod,
) -> sa.Select[tuple[int, str | None]]:
    method = FilterMethod(method)

    stmt = (
        sa.select(CacheTable.id, CacheTable.filepath)
        .where(
            CacheTable.id > sa.bindparam("lower_bound", type_=sa.Integer()),
            CacheTable.tag_names.in_(
                sa.bindparam("select_tags", type_=sa.String(), expanding=True)
            ),
        )
        .order_by(CacheTable.id.asc())
        .limit(100)
    )
    if method == FilterMethod.AND:
        stmt = stmt.group_by(CacheTable.id).having(
            CacheTable.tags_count == sa.bindparam("tags_count", type_=sa.Integer())
        )

    return stmt


def prepare_expire_stmt() -> sa.Select[tuple[int, str | None, float | None]]:
    return (
        sa.select(CacheTable.id, CacheTable.filepath, CacheTable.expire_time)
        .where(
            CacheTable.expire_time.is_not(None),
            CacheTable.expire_time > 0,
            CacheTable.expire_time < sa.bindparam("expire_time"),
        )
        .order_by(CacheTable.expire_time)
        .limit(100)
    )


def prepare_push_args(
    *,
    prefix: str | None = None,
    side: QueueSideLiteral | QueueSide = QueueSide.BACK,
    expire: float | None = None,
    tags: str | Iterable[str] | None = None,
) -> tuple[sa.Select[tuple[bytes]], float, float | None, set[str] | None]:
    side = QueueSide(side)
    if isinstance(tags, str):
        tags = [tags]
    if tags is not None:
        tags = set(tags)
    min_key, max_key = QUEUE_KEY_MINIMA, QUEUE_KEY_MAXIMA
    if prefix is not None:
        min_key, max_key = (f"{prefix}-{min_key}", f"{prefix}-{max_key}")
    min_key, max_key = str(min_key).encode(), str(max_key).encode()

    now = time.time()
    expire_time = None if expire is None else now + expire
    stmt = (
        sa.select(CacheTable.key)
        .select_from(CacheTable)
        .where(
            CacheTable.key > min_key, CacheTable.key < max_key, CacheTable.raw.is_(True)
        )
        .order_by(
            CacheTable.key.desc() if side == QueueSide.BACK else CacheTable.key.asc()
        )
        .limit(1)
    )

    return stmt, now, expire_time, tags


def find_push_key(
    *,
    prefix: str | None,
    side: QueueSideLiteral | QueueSide,
    db_key: bytes | None,
    stacklevel: int = 2,
) -> Any:
    if db_key is None:
        logger.debug("No key found, use default key", stacklevel=stacklevel)
        key = QUEUE_KEY_DEFAULT
    else:
        key = int(db_key) if prefix is None else int(db_key[db_key.rfind(b"-") + 1 :])
        if side == QueueSide.BACK:
            key += 1
        else:
            key -= 1
        logger.debug("Found key `%s`, use key `%d`", db_key, key)

    if prefix is None:
        return key
    return f"{prefix}-{key:0{len(str(QUEUE_KEY_MAXIMA))}d}"


def prepare_pull_or_peek_stmt(
    *, prefix: str | None = None, side: QueueSideLiteral | QueueSide = QueueSide.FRONT
) -> sa.Select[tuple[CacheTable]]:
    side = QueueSide(side)
    min_key, max_key = QUEUE_KEY_MINIMA, QUEUE_KEY_MAXIMA
    if prefix is not None:
        min_key, max_key = (f"{prefix}-{min_key}", f"{prefix}-{max_key}")
    min_key, max_key = str(min_key).encode(), str(max_key).encode()

    return (
        sa.select(CacheTable)
        .select_from(CacheTable)
        .where(
            CacheTable.key > min_key, CacheTable.key < max_key, CacheTable.raw.is_(True)
        )
        .order_by(
            CacheTable.key.desc() if side == QueueSide.BACK else CacheTable.key.asc()
        )
        .limit(1)
    )


def pull_process(
    *,
    conn: Connection,
    disk: DiskProtocol,
    stmt: sa.Select[tuple[CacheTable]],
    default: tuple[str, Any] | None,
    retry: bool,
) -> Container[Any] | tuple[CacheTable, Any, set[str]] | None:
    with transact(conn=conn, disk=disk, retry=retry) as (session, cleanup):
        row = session.scalars(stmt).one_or_none()
        if row is None:
            logger.debug("No key found, use default key")
            return Container(
                value=default[1] if default else None,
                key=default[0] if default else None,
                default=True,
            )

        tags = set(row.tag_names)
        session.delete(row)
        if (
            row.expire_time is not None
            and row.expire_time < time.time()
            and row.filepath
        ):
            cleanup([row.filepath])
            return None

        try:
            value = disk.fetch(mode=row.mode, filename=row.filepath, value=row.value)
        except OSError:
            return None
        finally:
            if row.filepath is not None:
                cleanup([row.filepath])
        return row, value, tags


async def apull_process(
    *,
    conn: Connection,
    disk: DiskProtocol,
    stmt: sa.Select[tuple[CacheTable]],
    default: tuple[str, Any] | None,
    retry: bool,
) -> Container[Any] | tuple[CacheTable, Any, set[str]] | None:
    async with async_transact(conn=conn, disk=disk, retry=retry) as (session, cleanup):
        row_fetch = await session.scalars(stmt)
        row = row_fetch.one_or_none()
        if row is None:
            logger.debug("No key found, use default key")
            return Container(
                value=default[1] if default else None,
                key=default[0] if default else None,
                default=True,
            )

        tags = await row.awaitable_attrs.tag_names
        tags = set(tags)
        await session.delete(row)
        if (
            row.expire_time is not None
            and row.expire_time < time.time()
            and row.filepath
        ):
            await cleanup([row.filepath])
            return None

        try:
            value = await disk.afetch(
                mode=row.mode, filename=row.filepath, value=row.value
            )
        except OSError:
            return None
        finally:
            if row.filepath is not None:
                await cleanup([row.filepath])
        return row, value, tags


def peek_process(
    *,
    conn: Connection,
    disk: DiskProtocol,
    stmt: sa.Select[tuple[CacheTable]],
    default: tuple[str, Any] | None,
    retry: bool,
) -> Container[Any] | tuple[CacheTable, Any, set[str]] | None:
    with transact(conn=conn, disk=disk, retry=retry) as (session, cleanup):
        row = session.scalars(stmt).one_or_none()
        if row is None:
            logger.debug("No key found, use default key")
            return Container(
                value=default[1] if default else None,
                key=default[0] if default else None,
                default=True,
            )

        tags = set(row.tag_names)
        if row.expire_time is not None and row.expire_time < time.time():
            session.delete(row)
            if row.filepath:
                cleanup([row.filepath])
            return None

        try:
            value = disk.fetch(mode=row.mode, filename=row.filepath, value=row.value)
        except OSError:
            logger.error("File not found: %s", row.filepath)  # noqa: TRY400
            session.delete(row)
            return None
        session.expunge(row)
        return row, value, tags


async def apeek_process(
    *,
    conn: Connection,
    disk: DiskProtocol,
    stmt: sa.Select[tuple[CacheTable]],
    default: tuple[str, Any] | None,
    retry: bool,
) -> Container[Any] | tuple[CacheTable, Any, set[str]] | None:
    async with async_transact(conn=conn, disk=disk, retry=retry) as (session, cleanup):
        row_fetch = await session.scalars(stmt)
        row = row_fetch.one_or_none()
        if row is None:
            logger.debug("No key found, use default key")
            return Container(
                value=default[1] if default else None,
                key=default[0] if default else None,
                default=True,
            )

        tags = await row.awaitable_attrs.tag_names
        tags = set(tags)
        if row.expire_time is not None and row.expire_time < time.time():
            await session.delete(row)
            if row.filepath:
                await cleanup([row.filepath])
            return None

        try:
            value = await disk.afetch(
                mode=row.mode, filename=row.filepath, value=row.value
            )
        except OSError:
            logger.error("File not found: %s", row.filepath)  # noqa: TRY400
            await session.delete(row)
            return None
        session.expunge(row)
        return row, value, tags


def peekitem_stmt(*, last: bool) -> sa.Select[tuple[CacheTable]]:
    return (
        sa.select(CacheTable)
        .select_from(CacheTable)
        .order_by(CacheTable.id.desc() if last else CacheTable.id.asc())
        .limit(1)
    )


def peekitem_process(
    *,
    conn: Connection,
    disk: DiskProtocol,
    stmt: sa.Select[tuple[CacheTable]],
    retry: bool,
) -> tuple[CacheTable, Any, set[str]] | None:
    with transact(conn=conn, disk=disk, retry=retry) as (session, cleanup):
        row = session.scalars(stmt).one_or_none()
        if row is None:
            raise te.TypedDiskcacheKeyError("Cache is empty")

        tags = set(row.tag_names)
        if row.expire_time is not None and row.expire_time < time.time():
            session.delete(row)
            if row.filepath:
                cleanup([row.filepath])
            return None

        try:
            value = disk.fetch(mode=row.mode, filename=row.filepath, value=row.value)
        except OSError:
            logger.error("File not found: %s", row.filepath)  # noqa: TRY400
            session.delete(row)
            return None

        session.expunge(row)
        return row, value, tags


async def apeekitem_process(
    *,
    conn: Connection,
    disk: DiskProtocol,
    stmt: sa.Select[tuple[CacheTable]],
    retry: bool,
) -> tuple[CacheTable, Any, set[str]] | None:
    async with async_transact(conn=conn, disk=disk, retry=retry) as (session, cleanup):
        row_fetch = await session.scalars(stmt)
        row = row_fetch.one_or_none()
        if row is None:
            raise te.TypedDiskcacheKeyError("Cache is empty")

        tags = await row.awaitable_attrs.tag_names
        tags = set(tags)
        if row.expire_time is not None and row.expire_time < time.time():
            await session.delete(row)
            if row.filepath:
                await cleanup([row.filepath])
            return None

        try:
            value = await disk.afetch(
                mode=row.mode, filename=row.filepath, value=row.value
            )
        except OSError:
            logger.error("File not found: %s", row.filepath)  # noqa: TRY400
            await session.delete(row)
            return None

        session.expunge(row)
        return row, value, tags


def prepare_iterkeys_stmt(
    *, reverse: bool
) -> tuple[sa.Select[tuple[bytes, bool]], sa.Select[tuple[bytes, bool]]]:
    select_stmt = (
        sa.select(CacheTable.key, CacheTable.raw)
        .select_from(CacheTable)
        .order_by(CacheTable.key.desc() if reverse else CacheTable.key.asc())
        .limit(1)
    )
    iter_key_bind = sa.bindparam("iter_key", type_=sa.LargeBinary())
    iter_stmt = (
        sa.select(CacheTable.key, CacheTable.raw)
        .select_from(CacheTable)
        .where(
            sa.or_(
                sa.and_(
                    CacheTable.key == iter_key_bind,
                    CacheTable.raw.is_not(sa.bindparam("iter_raw", type_=sa.Boolean())),
                ),
                (CacheTable.key < iter_key_bind)
                if reverse
                else (CacheTable.key > iter_key_bind),
            )
        )
        .order_by(CacheTable.key.desc() if reverse else CacheTable.key.asc())
        .limit(sa.bindparam("chunksize", type_=sa.Integer()))
    )

    return select_stmt, iter_stmt


async def acheck_integrity(*, conn: Connection, fix: bool, stacklevel: int = 2) -> None:
    async with conn.async_session as session:
        integrity_fetch = await session.execute(sa.text("PRAGMA integrity_check;"))
        integrity = integrity_fetch.scalars().all()

        if len(integrity) != 1 or integrity[0] != "ok":
            for message in integrity:
                warnings.warn(message, stacklevel=stacklevel)

        if fix:
            await session.execute(sa.text("VACUUM;"))


async def acheck_files(
    *,
    session: AsyncSession,
    directory: str | PathLike[str],
    fix: bool,
    stacklevel: int = 2,
) -> None:
    filenames: set[AnyioPath] = set()
    rows_fetch = await session.execute(
        sa.select(
            CacheTable.id,
            CacheTable.size,
            sa.func.cast(CacheTable.filepath, sa.String()),
        )
        .select_from(CacheTable)
        .where(CacheTable.filepath.is_not(None))
    )
    rows = rows_fetch.all()

    for row in rows:
        await acheck_file_exists(
            session=session,
            row=row,
            directory=directory,
            fix=fix,
            filenames=filenames,
            stacklevel=stacklevel + 1,
        )

    for dirpath, _, files in os.walk(directory):
        await acheck_unknown_file(
            dirpath=dirpath,
            fix=fix,
            files=files,
            filenames=filenames,
            stacklevel=stacklevel + 1,
        )

    for dirpath, dirs, files in os.walk(directory):
        await acheck_empty_dir(
            dirs=dirs, files=files, dirpath=dirpath, fix=fix, stacklevel=stacklevel + 1
        )


async def acheck_file_exists(  # noqa: PLR0913
    *,
    session: AsyncSession,
    row: sa.Row[tuple[int, int, str]],
    directory: str | PathLike[str],
    fix: bool,
    filenames: set[AnyioPath],
    stacklevel: int = 3,
) -> None:
    import anyio

    full_path: anyio.Path = anyio.Path(directory) / row.filepath
    filenames.add(full_path)

    if await full_path.exists():
        stats = await full_path.stat()
        real_size = stats.st_size

        if row.size != real_size:
            message = f"Size mismatch: {row.size} != {real_size}, {full_path}"
            warnings.warn(message, stacklevel=1)

            if fix:
                await session.execute(
                    sa.update(CacheTable)
                    .where(CacheTable.id == row.id)
                    .values(size=real_size)
                )
        return

    message = f"File not found: {full_path}"
    warnings.warn(message, stacklevel=stacklevel)

    if fix:
        await session.execute(sa.delete(CacheTable).where(CacheTable.id == row.id))


async def acheck_unknown_file(
    *,
    dirpath: str | PathLike[str],
    fix: bool,
    files: list[str],
    filenames: set[AnyioPath],
    stacklevel: int = 3,
) -> None:
    import anyio

    paths = {anyio.Path(dirpath) / file for file in files}
    error = paths - filenames

    for full_path in error:
        if full_path.name == DBNAME:
            continue

        message = f"Unknown file: {full_path}"
        warnings.warn(
            message, te.TypedDiskcacheUnknownFileWarning, stacklevel=stacklevel
        )

        if fix:
            await full_path.unlink()


async def acheck_empty_dir(
    *,
    dirs: list[str],
    files: list[str],
    dirpath: str | PathLike[str],
    fix: bool,
    stacklevel: int = 3,
) -> None:
    import anyio

    if not (dirs or files):
        message = f"Empty directory: {dirpath}"
        warnings.warn(message, te.TypedDiskcacheEmptyDirWarning, stacklevel=stacklevel)

        if fix:
            await anyio.Path(dirpath).rmdir()


async def acheck_metadata_count(
    *, session: AsyncSession, fix: bool, stacklevel: int = 2
) -> None:
    meta_count_fetch = await session.execute(
        sa.select(Metadata)
        .select_from(Metadata)
        .where(Metadata.key == MetadataKey.COUNT)
    )
    meta_count = meta_count_fetch.scalars().one()
    cache_count_fetch = await session.scalars(
        sa.select(sa.func.count(CacheTable.id)).select_from(CacheTable)
    )
    cache_count = cache_count_fetch.one()

    if meta_count.value != cache_count:
        message = f"Metadata count mismatch: {meta_count.value} != {cache_count}"
        warnings.warn(message, stacklevel=stacklevel)

        if fix:
            await session.execute(
                sa.update(Metadata)
                .values(value=cache_count)
                .where(Metadata.key == MetadataKey.COUNT)
            )


async def acheck_metadata_size(
    *, session: AsyncSession, fix: bool, stacklevel: int = 2
) -> None:
    meta_size_fetch = await session.execute(
        sa.select(Metadata)
        .select_from(Metadata)
        .where(Metadata.key == MetadataKey.SIZE)
    )
    meta_size = meta_size_fetch.scalars().one()
    cache_size_fetch = await session.scalars(
        sa.select(sa.func.coalesce(sa.func.sum(CacheTable.size), 0)).select_from(
            CacheTable
        )
    )
    cache_size = cache_size_fetch.one()

    if meta_size.value != cache_size:
        message = f"Metadata size mismatch: {meta_size.value} != {cache_size}"
        warnings.warn(message, stacklevel=stacklevel)

        if fix:
            await session.execute(
                sa.update(Metadata)
                .values(value=cache_size)
                .where(Metadata.key == MetadataKey.SIZE)
            )


def check_integrity(*, conn: Connection, fix: bool, stacklevel: int = 2) -> None:
    with conn.sync_session as session:
        integrity = session.execute(sa.text("PRAGMA integrity_check;")).scalars().all()

        if len(integrity) != 1 or integrity[0] != "ok":
            for message in integrity:
                warnings.warn(message, stacklevel=stacklevel)

        if fix:
            session.execute(sa.text("VACUUM;"))


def check_files(
    *, session: Session, directory: str | PathLike[str], fix: bool, stacklevel: int = 2
) -> None:
    filenames: set[Path] = set()
    rows = session.execute(
        sa.select(
            CacheTable.id,
            CacheTable.size,
            sa.func.cast(CacheTable.filepath, sa.String()),
        )
        .select_from(CacheTable)
        .where(CacheTable.filepath.is_not(None))
    ).all()

    for row in rows:
        check_file_exists(
            session=session,
            row=row,
            directory=directory,
            fix=fix,
            filenames=filenames,
            stacklevel=stacklevel + 1,
        )

    for dirpath, _, files in os.walk(directory):
        check_unknown_file(
            dirpath=dirpath,
            fix=fix,
            files=files,
            filenames=filenames,
            stacklevel=stacklevel + 1,
        )

    for dirpath, dirs, files in os.walk(directory):
        check_empty_dir(
            dirs=dirs, files=files, dirpath=dirpath, fix=fix, stacklevel=stacklevel + 1
        )


def check_file_exists(  # noqa: PLR0913
    *,
    session: Session,
    row: sa.Row[tuple[int, int, str]],
    directory: str | PathLike[str],
    fix: bool,
    filenames: set[Path],
    stacklevel: int = 3,
) -> None:
    full_path: Path = Path(directory) / row.filepath
    filenames.add(full_path)

    if full_path.exists():
        stats = full_path.stat()
        real_size = stats.st_size

        if row.size != real_size:
            message = f"Size mismatch: {row.size} != {real_size}, {full_path}"
            warnings.warn(message, stacklevel=1)

            if fix:
                session.execute(
                    sa.update(CacheTable)
                    .where(CacheTable.id == row.id)
                    .values(size=real_size)
                )
        return

    message = f"File not found: {full_path}"
    warnings.warn(message, stacklevel=stacklevel)

    if fix:
        session.execute(sa.delete(CacheTable).where(CacheTable.id == row.id))


def check_unknown_file(
    *,
    dirpath: str | PathLike[str],
    fix: bool,
    files: list[str],
    filenames: set[Path],
    stacklevel: int = 3,
) -> None:
    paths = {Path(dirpath) / file for file in files}
    error = paths - filenames

    for full_path in error:
        if full_path.name == DBNAME:
            continue

        message = f"Unknown file: {full_path}"
        warnings.warn(
            message, te.TypedDiskcacheUnknownFileWarning, stacklevel=stacklevel
        )

        if fix:
            full_path.unlink()


def check_empty_dir(
    *,
    dirs: list[str],
    files: list[str],
    dirpath: str | PathLike[str],
    fix: bool,
    stacklevel: int = 3,
) -> None:
    if not (dirs or files):
        message = f"Empty directory: {dirpath}"
        warnings.warn(message, te.TypedDiskcacheEmptyDirWarning, stacklevel=stacklevel)

        if fix:
            Path(dirpath).rmdir()


def check_metadata_count(*, session: Session, fix: bool, stacklevel: int = 2) -> None:
    meta_count = (
        session.execute(
            sa.select(Metadata)
            .select_from(Metadata)
            .where(Metadata.key == MetadataKey.COUNT)
        )
        .scalars()
        .one()
    )
    cache_count = session.scalars(
        sa.select(sa.func.count(CacheTable.id)).select_from(CacheTable)
    ).one()

    if meta_count.value != cache_count:
        message = f"Metadata count mismatch: {meta_count.value} != {cache_count}"
        warnings.warn(message, stacklevel=stacklevel)

        if fix:
            session.execute(
                sa.update(Metadata)
                .values(value=cache_count)
                .where(Metadata.key == MetadataKey.COUNT)
            )


def check_metadata_size(*, session: Session, fix: bool, stacklevel: int = 2) -> None:
    meta_size = (
        session.execute(
            sa.select(Metadata)
            .select_from(Metadata)
            .where(Metadata.key == MetadataKey.SIZE)
        )
        .scalars()
        .one()
    )
    cache_size = session.scalars(
        sa.select(sa.func.coalesce(sa.func.sum(CacheTable.size), 0)).select_from(
            CacheTable
        )
    ).one()

    if meta_size.value != cache_size:
        message = f"Metadata size mismatch: {meta_size.value} != {cache_size}"
        warnings.warn(message, stacklevel=stacklevel)

        if fix:
            session.execute(
                sa.update(Metadata)
                .values(value=cache_size)
                .where(Metadata.key == MetadataKey.SIZE)
            )


def prepare_update_settings_args(
    old_settings: Settings, new_settings: Settings
) -> tuple[Settings, dict[str, Any], sa.Update] | Settings:
    new_settings = old_settings.model_validate(new_settings)
    new_settings_dict = new_settings.model_dump(
        exclude={"sqlite_settings"}, by_alias=True
    )
    update_settings = {
        key: value
        for key, value in new_settings_dict.items()
        if getattr(old_settings, key) != value
    }

    old_sqlite_settings = old_settings.sqlite_settings.model_dump(by_alias=True)
    new_sqlite_settings = new_settings.sqlite_settings.model_dump(by_alias=True)
    update_sqlite_settings: dict[str, Any] = {
        key: value
        for key, value in new_sqlite_settings.items()
        if old_sqlite_settings[key] != value
    }
    if not update_settings and not update_sqlite_settings:
        logger.debug("No settings to update")
        return new_settings

    update_stmt = (
        sa.update(SettingsTable)
        .where(SettingsTable.key == sa.bindparam("settings_key"))
        .values(value=sa.bindparam("settings_value"))
    )

    return new_settings, update_settings | update_sqlite_settings, update_stmt
