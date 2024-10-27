from __future__ import annotations

import time
from contextlib import AsyncExitStack, ExitStack
from typing import TYPE_CHECKING, Any

from pydantic import TypeAdapter
from typing_extensions import override

from typed_diskcache import exception as te
from typed_diskcache.core.const import DEFAULT_LOCK_TIMEOUT, SPIN_LOCK_SLEEP
from typed_diskcache.core.context import context
from typed_diskcache.database.connect import transact
from typed_diskcache.interface.sync import AsyncSemaphoreProtocol, SyncSemaphoreProtocol
from typed_diskcache.log import get_logger

if TYPE_CHECKING:
    from collections.abc import Iterable
    from types import TracebackType

    from typed_diskcache.interface.cache import CacheProtocol

__all__ = ["SyncSemaphore", "AsyncSemaphore"]

logger = get_logger()
_SEMAPHORE_VALUE_ADAPTER = TypeAdapter(int)


class SyncSemaphore(SyncSemaphoreProtocol):
    """Semaphore implementation using spin-lock algorithm."""

    __slots__ = ("_cache", "_key", "_value", "_timeout", "_expire", "_tags")

    def __init__(  # noqa: PLR0913
        self,
        cache: CacheProtocol,
        key: Any,
        value: int = 1,
        *,
        timeout: float = DEFAULT_LOCK_TIMEOUT,
        expire: float | None = None,
        tags: str | Iterable[str] | None = None,
    ) -> None:
        self._cache = cache
        self._key = key
        self._value = value
        self._timeout = timeout
        self._expire = expire
        self._tags = frozenset() if tags is None else frozenset(tags)

    @property
    @override
    def key(self) -> Any:
        return self._key

    @property
    @override
    def value(self) -> int:
        return self._value

    @property
    @override
    def timeout(self) -> float:
        return self._timeout

    @property
    @override
    def expire(self) -> float | None:
        return self._expire

    @property
    @override
    def tags(self) -> frozenset[str]:
        return self._tags

    @context("SyncSemaphore.acquire", override=True)
    @context("SyncSemaphore.acquire")
    @override
    def acquire(self) -> None:
        start = time.monotonic()
        timeout = 0
        with ExitStack() as stack:
            while timeout < self.timeout:
                session = stack.enter_context(self._cache.conn.sync_session)
                stack.enter_context(transact(session))
                container = self._cache.get(self.key, default=self._value)
                container_value = validate_semaphore_value(container.value)
                if container_value > 0:
                    self._cache.set(
                        self.key,
                        container_value - 1,
                        expire=self.expire,
                        tags=self.tags,
                    )
                    return
                stack.close()
                time.sleep(SPIN_LOCK_SLEEP)
                timeout = time.monotonic() - start

        raise te.TypedDiskcacheTimeoutError("lock acquire timeout")

    @context("SyncSemaphore.release", override=True)
    @context("SyncSemaphore.release")
    @override
    def release(self) -> None:
        with ExitStack() as stack:
            session = stack.enter_context(self._cache.conn.sync_session)
            stack.enter_context(transact(session))
            container = self._cache.get(self.key, default=self._value)
            container_value = validate_semaphore_value(container.value)
            if self._value <= container_value:
                logger.error(
                    "cannot release un-acquired semaphore, value: %d, container: %d",
                    self._value,
                    container_value,
                )
                raise te.TypedDiskcacheRuntimeError(
                    "cannot release un-acquired semaphore"
                )
            self._cache.set(
                self.key, container_value + 1, expire=self.expire, tags=self.tags
            )

    @override
    def __enter__(self) -> None:
        self.acquire()

    @override
    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_value: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        self.release()


class AsyncSemaphore(AsyncSemaphoreProtocol):
    """Asynchronous semaphore implementation using spin-lock algorithm."""

    __slots__ = ("_cache", "_key", "_value", "_expire", "_tags")

    def __init__(  # noqa: PLR0913
        self,
        cache: CacheProtocol,
        key: Any,
        value: int = 1,
        *,
        timeout: float = DEFAULT_LOCK_TIMEOUT,
        expire: float | None = None,
        tags: str | Iterable[str] | None = None,
    ) -> None:
        self._cache = cache
        self._key = key
        self._value = value
        self._timeout = timeout
        self._expire = expire
        self._tags = frozenset() if tags is None else frozenset(tags)

    @property
    @override
    def key(self) -> Any:
        return self._key

    @property
    @override
    def value(self) -> int:
        return self._value

    @property
    @override
    def timeout(self) -> float:
        return self._timeout

    @property
    @override
    def expire(self) -> float | None:
        return self._expire

    @property
    @override
    def tags(self) -> frozenset[str]:
        return self._tags

    @context("AsyncSemaphore.acquire", override=True)
    @context("AsyncSemaphore.acquire")
    @override
    async def acquire(self) -> None:
        import anyio

        try:
            async with AsyncExitStack() as stack:
                stack.enter_context(anyio.fail_after(self.timeout))
                sub_stack = await stack.enter_async_context(AsyncExitStack())
                while True:
                    session = await sub_stack.enter_async_context(
                        self._cache.conn.async_session
                    )
                    await sub_stack.enter_async_context(transact(session))
                    container = await self._cache.aget(self.key, default=self._value)
                    container_value = validate_semaphore_value(container.value)
                    if container_value > 0:
                        await self._cache.aset(
                            self.key,
                            container_value - 1,
                            expire=self.expire,
                            tags=self.tags,
                        )
                        return
                    await sub_stack.aclose()
                    await anyio.sleep(SPIN_LOCK_SLEEP)
        except TimeoutError as exc:
            raise te.TypedDiskcacheTimeoutError("lock acquire timeout") from exc

    @context("AsyncSemaphore.release", override=True)
    @context("AsyncSemaphore.release")
    @override
    async def release(self) -> None:
        async with AsyncExitStack() as stack:
            session = await stack.enter_async_context(self._cache.conn.async_session)
            await stack.enter_async_context(transact(session))
            container = await self._cache.aget(self.key, default=self._value)
            container_value = validate_semaphore_value(container.value)
            if self._value <= container_value:
                logger.error(
                    "cannot release un-acquired semaphore, value: %d, container: %d",
                    self._value,
                    container_value,
                )
                raise te.TypedDiskcacheRuntimeError(
                    "cannot release un-acquired semaphore"
                )
            await self._cache.aset(
                self.key, container_value + 1, expire=self.expire, tags=self.tags
            )

    @override
    async def __aenter__(self) -> None:
        await self.acquire()

    @override
    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_value: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        await self.release()


def validate_semaphore_value(value: Any) -> int:
    try:
        return _SEMAPHORE_VALUE_ADAPTER.validate_python(value)
    except ValueError as exc:
        raise te.TypedDiskcacheTypeError("invalid semaphore value") from exc
