from __future__ import annotations

from contextlib import (
    AbstractAsyncContextManager,
    AbstractContextManager,
    asynccontextmanager,
    contextmanager,
    suppress,
)
from typing import TYPE_CHECKING, Any, Callable, Protocol, overload, runtime_checkable

import sqlalchemy as sa
from sqlalchemy.dialects.sqlite import dialect as sqlite_dialect
from sqlalchemy.engine import Connection, Engine, create_engine
from sqlalchemy.engine.url import URL, make_url
from sqlalchemy.event import listen
from sqlalchemy.exc import ResourceClosedError
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    create_async_engine,
)
from sqlalchemy.orm import Session
from typing_extensions import TypeVar

from typed_diskcache import exception as te
from typed_diskcache.core.const import CONNECTION_BEGIN_INFO_KEY
from typed_diskcache.log import get_logger

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator

    from _typeshed import StrPath
    from sqlalchemy.engine.interfaces import DBAPIConnection, Dialect

    from typed_diskcache.model import SQLiteSettings

__all__ = [
    "create_sqlite_url",
    "ensure_sqlite_sync_engine",
    "ensure_sqlite_async_engine",
    "transact",
    "set_listeners",
]

AsyncConnT = TypeVar(
    "AsyncConnT", bound="AsyncSession | AsyncConnection", infer_variance=True
)
SyncConnT = TypeVar("SyncConnT", bound="Session | Connection", infer_variance=True)
SessionT = TypeVar("SessionT", bound="Session | AsyncSession", infer_variance=True)

_TIMEOUT = 10
_TIMEOUT_MS = _TIMEOUT * 1000

logger = get_logger()


@runtime_checkable
class SessionMaker(Protocol[SessionT]):
    """callable what return sqlalchemy session"""

    __call__: Callable[..., SessionT]


def create_sqlite_url(file: StrPath, *, is_async: bool = False, **kwargs: Any) -> URL:
    """file to sqlite url"""
    url = URL.create(drivername="sqlite+pysqlite")
    if is_async:
        url = url.set(drivername="sqlite+aiosqlite")

    url = url.set(**kwargs).set(database=str(file))
    return ensure_sqlite_url(url, is_async=is_async)


def ensure_sqlite_url(url: str | URL, *, is_async: bool = False) -> URL:
    """string to sqlite url"""
    url = make_url(url)
    dialect = url.get_dialect()
    if dialect.name != sqlite_dialect.name:
        error_msg = f"not sqlite dialect: {dialect.name}"
        raise te.TypedDiskcacheError(error_msg)

    if _is_async_dialect(dialect) is not is_async:
        driver = url.get_driver_name()
        if not driver and is_async:
            url = url.set(drivername=f"{dialect.name}+aiosqlite")
        else:
            error_msg = f"not async dialect: {driver}"
            raise te.TypedDiskcacheError(error_msg)

    return url


@overload
def ensure_sqlite_engine(connectable_or_url: URL | str) -> Engine | AsyncEngine: ...


@overload
def ensure_sqlite_engine(
    connectable_or_url: Engine
    | Connection
    | SessionMaker[Session]
    | Session
    | URL
    | str,
) -> Engine: ...


@overload
def ensure_sqlite_engine(
    connectable_or_url: AsyncEngine
    | AsyncConnection
    | SessionMaker[AsyncSession]
    | AsyncSession
    | URL
    | str,
) -> AsyncEngine: ...


@overload
def ensure_sqlite_engine(
    connectable_or_url: Engine
    | AsyncEngine
    | AsyncConnection
    | SessionMaker[AsyncSession]
    | AsyncSession
    | Connection
    | SessionMaker[Session]
    | Session
    | URL
    | str,
) -> Engine | AsyncEngine: ...


def ensure_sqlite_engine(
    connectable_or_url: Engine
    | AsyncEngine
    | AsyncConnection
    | SessionMaker[AsyncSession]
    | AsyncSession
    | Connection
    | SessionMaker[Session]
    | Session
    | URL
    | str,
) -> Engine | AsyncEngine:
    """ensure sqlalchemy sqlite engine"""
    if isinstance(connectable_or_url, (AsyncEngine, AsyncConnection, AsyncSession)):
        return ensure_sqlite_async_engine(connectable_or_url)
    if isinstance(connectable_or_url, (Engine, Connection, Session)):
        return ensure_sqlite_sync_engine(connectable_or_url)
    if isinstance(connectable_or_url, str):
        connectable_or_url = ensure_sqlite_url(connectable_or_url)
    if isinstance(connectable_or_url, URL):
        dialect = connectable_or_url.get_dialect()
        if _is_async_dialect(dialect):
            return ensure_sqlite_async_engine(connectable_or_url)
        return ensure_sqlite_sync_engine(connectable_or_url)
    if isinstance(connectable_or_url, SessionMaker):
        connectable_or_url = connectable_or_url()
        return ensure_sqlite_engine(connectable_or_url)

    error_msg = f"invalid connectable type: {type(connectable_or_url).__name__}"
    raise te.FernetSecretsTypeError(error_msg)


def ensure_sqlite_sync_engine(
    connectable_or_url: Engine
    | Connection
    | SessionMaker[Session]
    | Session
    | URL
    | str,
) -> Engine:
    """ensure sqlalchemy sqlite sync engine"""
    if isinstance(connectable_or_url, (Engine, Connection)):
        return ensure_sqlite_sync_engine(connectable_or_url.engine.url)

    if isinstance(connectable_or_url, (str, URL)):
        connectable_or_url = ensure_sqlite_url(connectable_or_url, is_async=False)

    if isinstance(connectable_or_url, URL):
        return _set_listeners(
            create_engine(
                connectable_or_url,
                connect_args={"timeout": _TIMEOUT, "isolation_level": None},
                poolclass=sa.NullPool,
            )
        )

    if isinstance(connectable_or_url, SessionMaker):
        connectable_or_url = connectable_or_url()

    if isinstance(connectable_or_url, Session):
        bind = connectable_or_url.get_bind()
        return ensure_sqlite_sync_engine(bind)

    error_msg = f"invalid sync connectable type: {type(connectable_or_url).__name__}"
    raise te.FernetSecretsTypeError(error_msg)


def ensure_sqlite_async_engine(
    connectable_or_url: AsyncEngine
    | AsyncConnection
    | SessionMaker[AsyncSession]
    | AsyncSession
    | URL
    | str,
) -> AsyncEngine:
    """ensure sqlalchemy sqlite async engine"""
    if isinstance(connectable_or_url, (AsyncEngine, AsyncConnection)):
        return ensure_sqlite_async_engine(connectable_or_url.engine.url)

    if isinstance(connectable_or_url, AsyncSession):
        bind = connectable_or_url.get_bind()
        return ensure_sqlite_async_engine(bind.engine.url)

    if isinstance(connectable_or_url, (str, URL)):
        connectable_or_url = ensure_sqlite_url(connectable_or_url, is_async=True)

    if isinstance(connectable_or_url, URL):
        return _set_listeners(
            create_async_engine(
                connectable_or_url,
                connect_args={"timeout": _TIMEOUT, "isolation_level": None},
                poolclass=sa.NullPool,
            )
        )

    if isinstance(connectable_or_url, SessionMaker):
        connectable_or_url = connectable_or_url()

    error_msg = f"invalid async connectable type: {type(connectable_or_url).__name__}"
    raise te.TypedDiskcacheTypeError(error_msg)


@contextmanager
def sync_transact(session: SyncConnT) -> Generator[SyncConnT, None, None]:
    conn = session.connection() if isinstance(session, Session) else session

    is_begin = conn.info.get(CONNECTION_BEGIN_INFO_KEY, False)
    if is_begin is False:
        conn.execute(sa.text("BEGIN IMMEDIATE;"))
        conn.info[CONNECTION_BEGIN_INFO_KEY] = True

    try:
        yield session
    except Exception:
        conn.rollback()
        raise
    finally:
        with suppress(ResourceClosedError):
            conn.info[CONNECTION_BEGIN_INFO_KEY] = False


@asynccontextmanager
async def async_transact(session: AsyncConnT) -> AsyncGenerator[AsyncConnT, None]:
    if isinstance(session, AsyncSession):
        conn = await session.connection()
    else:
        conn = session

    is_begin = conn.info.get(CONNECTION_BEGIN_INFO_KEY, False)
    if is_begin is False:
        await conn.execute(sa.text("BEGIN IMMEDIATE;"))
        conn.info[CONNECTION_BEGIN_INFO_KEY] = True

    try:
        yield session
    except Exception:
        await conn.rollback()
        raise
    finally:
        with suppress(ResourceClosedError):
            conn.info[CONNECTION_BEGIN_INFO_KEY] = False


@overload
def transact(session: SyncConnT) -> AbstractContextManager[SyncConnT]: ...
@overload
def transact(session: AsyncConnT) -> AbstractAsyncContextManager[AsyncConnT]: ...
@overload
def transact(
    session: SyncConnT | AsyncConnT,
) -> AbstractContextManager[SyncConnT] | AbstractAsyncContextManager[AsyncConnT]: ...
def transact(
    session: SyncConnT | AsyncConnT,
) -> AbstractContextManager[SyncConnT] | AbstractAsyncContextManager[AsyncConnT]:
    """transaction context manager"""
    if isinstance(session, (AsyncSession, AsyncConnection)):
        return async_transact(session)
    return sync_transact(session)


@overload
def set_listeners(engine: Engine, settings: SQLiteSettings) -> Engine: ...
@overload
def set_listeners(engine: AsyncEngine, settings: SQLiteSettings) -> AsyncEngine: ...
@overload
def set_listeners(
    engine: Engine | AsyncEngine, settings: SQLiteSettings
) -> Engine | AsyncEngine: ...
def set_listeners(
    engine: Engine | AsyncEngine, settings: SQLiteSettings
) -> Engine | AsyncEngine:
    """set sqlite listeners"""
    sync_engine = engine.sync_engine if isinstance(engine, AsyncEngine) else engine
    listen(sync_engine, "connect", settings.listen_connect)
    return engine


def _is_async_dialect(dialect: type[Dialect] | Dialect) -> bool:
    return getattr(dialect, "is_async", False) is True


def _sqlite_busy_timeout(
    dbapi_connection: DBAPIConnection,
    connection_record: Any,  # noqa: ARG001
) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute(f"PRAGMA busy_timeout = {_TIMEOUT_MS!s};", ())


def _sqlite_foreign_keys(
    dbapi_connection: DBAPIConnection,
    connection_record: Any,  # noqa: ARG001
) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;", ())


@overload
def _set_listeners(engine: Engine) -> Engine: ...
@overload
def _set_listeners(engine: AsyncEngine) -> AsyncEngine: ...
@overload
def _set_listeners(engine: Engine | AsyncEngine) -> Engine | AsyncEngine: ...
def _set_listeners(engine: Engine | AsyncEngine) -> Engine | AsyncEngine:
    sync_engine = engine.sync_engine if isinstance(engine, AsyncEngine) else engine
    listen(sync_engine, "connect", _sqlite_busy_timeout)
    listen(sync_engine, "connect", _sqlite_foreign_keys)
    return engine
