from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager, suppress
from contextvars import Context, ContextVar
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession
from sqlalchemy.orm import Session

from typed_diskcache import exception as te
from typed_diskcache.core.context import enter_session
from typed_diskcache.core.types import EvictionPolicy
from typed_diskcache.database import connect as db_connect
from typed_diskcache.database.model import Cache
from typed_diskcache.log import get_logger
from typed_diskcache.utils.dependency import validate_installed

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator, Mapping
    from os import PathLike

    from sqlalchemy.engine import Connection as SAConnection

    from typed_diskcache.model import Settings


__all__ = ["Connection"]

logger = get_logger()


class Connection:
    """Database connection."""

    def __init__(
        self,
        database: str | PathLike[str],
        timeout: float,
        settings: Settings | None = None,
    ) -> None:
        self._database = Path(database)
        self._timeout = timeout

        self._settings = settings

        self_id = id(self)
        self._context: ContextVar[Session | None] = ContextVar(
            f"{self_id}-session", default=None
        )
        self._acontext: ContextVar[AsyncSession | None] = ContextVar(
            f"{self_id}-asession", default=None
        )

    def __getstate__(self) -> Mapping[str, Any]:
        return {
            "database": str(self._database),
            "timeout": self._timeout,
            "settings": None
            if self._settings is None
            else self._settings.model_dump_json(),
        }

    def __setstate__(self, state: Mapping[str, Any]) -> None:
        from typed_diskcache.model import Settings

        self._database = Path(state["database"])
        self.timeout = state["timeout"]
        self._settings = (
            None
            if state["settings"] is None
            else Settings.model_validate_json(state["settings"])
        )

        self_id = id(self)
        if not hasattr(self, "_context"):
            self._context = ContextVar(f"{self_id}-session", default=None)
        if not hasattr(self, "_acontext"):
            self._acontext = ContextVar(f"{self_id}-asession", default=None)

    @property
    def timeout(self) -> float:
        """Return the timeout."""
        return self._timeout

    @timeout.setter
    def timeout(self, value: float) -> None:
        """Set the timeout."""
        self._timeout = value

    @cached_property
    def _sync_url(self) -> sa.URL:
        return db_connect.create_sqlite_url(self._database, is_async=False)

    @cached_property
    def _async_url(self) -> sa.URL:
        return db_connect.create_sqlite_url(self._database, is_async=True)

    @cached_property
    def _sync_engine(self) -> sa.Engine:
        engine = db_connect.ensure_sqlite_sync_engine(self._sync_url)
        if self._settings is None:
            return engine

        return db_connect.set_listeners(engine, self._settings.sqlite_settings)

    @cached_property
    def _async_engine(self) -> AsyncEngine:
        engine = db_connect.ensure_sqlite_async_engine(self._async_url)
        if self._settings is None:
            return engine

        return db_connect.set_listeners(engine, self._settings.sqlite_settings)

    @contextmanager
    def _connect(self, *, stacklevel: int = 1) -> Generator[SAConnection, None, None]:
        with self._sync_engine.connect() as connection:
            logger.debug(
                "Creating connection: `%d`", id(connection), stacklevel=stacklevel
            )
            yield connection
            logger.debug(
                "Closing connection: `%d`", id(connection), stacklevel=stacklevel
            )

    @contextmanager
    def session(self, *, stacklevel: int = 1) -> Generator[Session, None, None]:
        """Connect to the database."""
        session = self._context.get()
        if session is not None:
            logger.debug("Reusing session: `%d`", id(session), stacklevel=stacklevel)
            yield session
            return

        with self._connect(stacklevel=stacklevel + 2) as connection:
            with Session(connection, autoflush=False) as session:
                logger.debug(
                    "Creating session: `%d`", id(session), stacklevel=stacklevel
                )
                yield session
                logger.debug(
                    "Closing session: `%d`", id(session), stacklevel=stacklevel
                )

    @asynccontextmanager
    async def _aconnect(
        self, *, stacklevel: int = 1
    ) -> AsyncGenerator[AsyncConnection, None]:
        """Connect to the database."""
        async with self._async_engine.connect() as connection:
            logger.debug(
                "Creating async connection: `%d`", id(connection), stacklevel=stacklevel
            )
            yield connection
            logger.debug(
                "Closing async connection: `%d`", id(connection), stacklevel=stacklevel
            )

    @asynccontextmanager
    async def asession(
        self, *, stacklevel: int = 1
    ) -> AsyncGenerator[AsyncSession, None]:
        """Connect to the database."""
        validate_installed("anyio", "Consider installing extra `asyncio`.")
        import anyio.lowlevel

        session = self._acontext.get()
        if session is not None:
            logger.debug(
                "Reusing async session: `%d`", id(session), stacklevel=stacklevel
            )
            await anyio.lowlevel.checkpoint()
            yield session
            return

        async with self._aconnect(stacklevel=stacklevel + 2) as connection:
            async with AsyncSession(connection, autoflush=False) as session:
                logger.debug(
                    "Creating async session: `%d`", id(session), stacklevel=stacklevel
                )
                yield session
                logger.debug(
                    "Closing async session: `%d`", id(session), stacklevel=stacklevel
                )

    def close(self) -> None:
        """Close the connection."""
        if "_sync_engine" in self.__dict__:
            self._sync_engine.dispose(close=True)
        if "_async_engine" in self.__dict__:
            self._async_engine.sync_engine.dispose(close=True)
        for key in (
            "_sync_engine",
            "_async_engine",
            "_sync_registry",
            "_async_registry",
        ):
            self.__dict__.pop(key, None)

    async def aclose(self) -> None:
        """Close the connection."""
        if "_sync_engine" in self.__dict__:
            self._sync_engine.dispose(close=True)
        if "_async_engine" in self.__dict__:
            await self._async_engine.dispose(close=True)
        for key in (
            "_sync_engine",
            "_async_engine",
            "_sync_registry",
            "_async_registry",
        ):
            self.__dict__.pop(key, None)

    def update_settings(self, settings: Settings) -> None:
        """Update the settings."""
        self.close()
        self._settings = settings

    @contextmanager
    def enter_session(
        self, session: Session | AsyncSession
    ) -> Generator[Context, None, None]:
        """Enter the session context.

        Args:
            session: The session to enter.

        Yields:
            Copy of the current context.
        """
        context_var = (
            self._acontext if isinstance(session, AsyncSession) else self._context
        )
        logger.debug(
            "Entering session context: `%s`, session: `%d`",
            context_var.name,
            id(session),
        )
        with enter_session(session, context_var) as context:  # pyright: ignore[reportArgumentType]
            yield context

    @property
    def eviction(self) -> Eviction:
        """Return the eviction policy manager."""
        return Eviction(self)

    def __del__(self) -> None:
        with suppress(BaseException):
            self.close()


class Eviction:
    def __init__(self, conn: Connection) -> None:
        if conn._settings is None:  # noqa: SLF001
            raise te.TypedDiskcacheValueError("settings is not set")

        self._conn = conn
        self._policy = conn._settings.eviction_policy  # noqa: SLF001

    @property
    def get(self) -> sa.Update | None:
        if self._policy == EvictionPolicy.LEAST_RECENTLY_USED:
            return (
                sa.update(Cache)
                .values(access_time=sa.bindparam("access_time", type_=sa.Float()))
                .where(Cache.id == sa.bindparam("id", type_=sa.Integer()))
            )
        if self._policy == EvictionPolicy.LEAST_FREQUENTLY_USED:
            return (
                sa.update(Cache)
                .values(access_count=sa.bindparam("access_count", type_=sa.Integer()))
                .where(Cache.id == sa.bindparam("id", type_=sa.Integer()))
            )
        return None

    @property
    def cull(self) -> sa.Select[tuple[Cache]] | None:
        if self._policy == EvictionPolicy.LEAST_RECENTLY_STORED:
            return (
                sa.select(Cache)
                .order_by(Cache.store_time)
                .limit(sa.bindparam("limit", type_=sa.Integer()))
            )
        if self._policy == EvictionPolicy.LEAST_RECENTLY_USED:
            return (
                sa.select(Cache)
                .order_by(Cache.access_time)
                .limit(sa.bindparam("limit", type_=sa.Integer()))
            )
        if self._policy == EvictionPolicy.LEAST_FREQUENTLY_USED:
            return (
                sa.select(Cache)
                .order_by(Cache.access_count)
                .limit(sa.bindparam("limit", type_=sa.Integer()))
            )
        return None
