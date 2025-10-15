from __future__ import annotations

import os
import threading
import time
import warnings
from contextlib import AsyncExitStack, ExitStack
from typing import TYPE_CHECKING, Any

from pydantic import TypeAdapter
from typing_extensions import override

from typed_diskcache import exception as te
from typed_diskcache.core.const import (
    DEFAULT_LOCK_TIMEOUT,
    IS_FREE_THREAD,
    SPIN_LOCK_SLEEP,
)
from typed_diskcache.core.context import context
from typed_diskcache.database.connect import transact
from typed_diskcache.interface.sync import AsyncLockProtocol, SyncLockProtocol
from typed_diskcache.log import get_logger
from typed_diskcache.utils.dependency import validate_installed

if TYPE_CHECKING:
    from collections.abc import Iterable
    from types import TracebackType

    from typed_diskcache.interface.cache import CacheProtocol

__all__ = ["AsyncLock", "AsyncRLock", "SyncLock", "SyncRLock"]

logger = get_logger()
_LOCK_VALUE_ADAPTER = TypeAdapter(tuple[str, int])


class SyncLock(SyncLockProtocol):
    """Lock implementation using spin-lock algorithm.

    Assumes the key will not be evicted. Set the eviction policy to 'none' on
    the cache to guarantee the key is not evicted.

    Args:
        cache: Cache to use for lock.
        key: Key for lock.
        timeout: Timeout for lock.
        expire: Expiration time for lock.
        tags: Tags for lock.

    Examples:
        ```python
        import typed_diskcache


        def main() -> None:
            cache = typed_diskcache.Cache()
            lock = typed_diskcache.SyncLock(cache, "some-key")
            lock.acquire()
            lock.release()
            with lock:
                pass
        ```
    """

    __slots__ = ("_cache", "_expire", "_key", "_tags", "_timeout")

    def __init__(
        self,
        cache: CacheProtocol,
        key: Any,
        *,
        timeout: float = DEFAULT_LOCK_TIMEOUT,
        expire: float | None = None,
        tags: str | Iterable[str] | None = None,
    ) -> None:
        self._cache = cache
        self._key = key
        self._timeout = timeout
        self._expire = expire
        self._tags = frozenset() if tags is None else frozenset(tags)

    @property
    @override
    def key(self) -> Any:
        return self._key

    @property
    @override
    def expire(self) -> float | None:
        return self._expire

    @property
    @override
    def timeout(self) -> float:
        return self._timeout

    @property
    @override
    def tags(self) -> frozenset[str]:
        return self._tags

    @property
    @override
    def locked(self) -> bool:
        return self.key in self._cache

    @context
    @override
    def acquire(self) -> None:
        start = time.monotonic()
        timeout = 0
        while timeout < self.timeout:
            added = self._cache.add(
                self.key, None, expire=self.expire, tags=self.tags, retry=True
            )
            if added:
                return
            time.sleep(SPIN_LOCK_SLEEP)
            timeout = time.monotonic() - start

        raise te.TypedDiskcacheTimeoutError("lock acquire timeout")

    @context
    @override
    def release(self) -> None:
        self._cache.delete(self.key, retry=True)

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


class SyncRLock(SyncLock):
    """Re-entrant lock implementation using spin-lock algorithm.

    Assumes the key will not be evicted. Set the eviction policy to 'none' on
    the cache to guarantee the key is not evicted.

    Args:
        cache: Cache to use for lock.
        key: Key for lock.
        timeout: Timeout for lock.
        expire: Expiration time for lock.
        tags: Tags for lock.

    Examples:
        ```python
        import typed_diskcache


        def main() -> None:
            cache = typed_diskcache.Cache()
            lock = typed_diskcache.SyncLock(cache, "some-key")
            lock.acquire()
            lock.release()
            with lock:
                pass
        ```
    """

    @context
    @override
    def acquire(self) -> None:
        pid = os.getpid()
        tid = threading.get_native_id()
        pid_tid = f"{pid}-{tid}"
        start = time.monotonic()
        timeout = 0

        with ExitStack() as stack:
            session = stack.enter_context(self._cache.conn.session(stacklevel=4))
            sub_stack = stack.enter_context(ExitStack())
            while timeout < self.timeout:
                sub_stack.enter_context(transact(session))
                context = sub_stack.enter_context(
                    self._cache.conn.enter_session(session)
                )
                container = context.run(
                    self._cache.get, self.key, default=("default", 0)
                )
                container_value = validate_lock_value(container.value)
                if (
                    container.default
                    or pid_tid == container_value[0]
                    or container_value[1] <= 0
                ):
                    value = 1 if container.default else container_value[1] + 1
                    logger.debug("acquired lock: %s, value: %d", pid_tid, value)
                    context.run(
                        self._cache.set,
                        self.key,
                        (pid_tid, value),
                        expire=self.expire,
                        tags=self.tags,
                    )
                    return
                logger.debug(
                    "Invalid lock: expected: `%s`, value: `%s`",
                    pid_tid,
                    container_value,
                )
                sub_stack.close()
                time.sleep(SPIN_LOCK_SLEEP)
                timeout = time.monotonic() - start

        raise te.TypedDiskcacheTimeoutError("lock acquire timeout")

    @context
    @override
    def release(self) -> None:
        pid = os.getpid()
        tid = threading.get_native_id()
        pid_tid = f"{pid}-{tid}"

        with ExitStack() as stack:
            logger.debug("releasing lock: %s", pid_tid)
            session = stack.enter_context(self._cache.conn.session(stacklevel=4))
            stack.enter_context(transact(session))
            context = stack.enter_context(self._cache.conn.enter_session(session))
            container = context.run(self._cache.get, self.key, default=("default", 0))
            container_value = validate_lock_value(container.value)
            if (
                container.default
                or container_value[0] != pid_tid
                or container_value[1] <= 0
            ):
                logger.error(
                    "cannot release un-acquired lock, id: %s, default: %s, value: %s",
                    pid_tid,
                    container.default,
                    container_value,
                )
                raise te.TypedDiskcacheRuntimeError("cannot release un-acquired lock")
            context.run(
                self._cache.set,
                self.key,
                (container_value[0], container_value[1] - 1),
                expire=self.expire,
                tags=self.tags,
            )


class AsyncLock(AsyncLockProtocol):
    """Lock implementation using spin-lock algorithm.

    Assumes the key will not be evicted. Set the eviction policy to 'none' on
    the cache to guarantee the key is not evicted.

    Asynchronous version of [`SyncLock`][typed_diskcache.SyncLock].

    Args:
        cache: Cache to use for lock.
        key: Key for lock.
        timeout: Timeout for lock.
        expire: Expiration time for lock.
        tags: Tags for lock.

    Warns:
        RuntimeWarning:
            If the current Python interpreter is free-threading (without GIL),
            using [`AsyncLock`][typed_diskcache.AsyncLock] may lead to
            unexpected behavior. Consider using
            [`SyncLock`][typed_diskcache.SyncLock] instead in such cases.

    Examples:
        ```python
        import typed_diskcache


        async def main() -> None:
            cache = typed_diskcache.Cache()
            lock = typed_diskcache.AsyncLock(cache, "some-key")
            await lock.acquire()
            await lock.release()
            async with lock:
                pass
        ```
    """

    __slots__ = ("_cache", "_expire", "_key", "_tags", "_timeout")

    def __init__(
        self,
        cache: CacheProtocol,
        key: Any,
        *,
        timeout: float = DEFAULT_LOCK_TIMEOUT,
        expire: float | None = None,
        tags: str | Iterable[str] | None = None,
    ) -> None:
        if IS_FREE_THREAD:
            message = (
                "The current Python interpreter is free-threading (without GIL). "
                "However, AsyncLock does not support free-threading mode. "
                "Consider using SyncLock instead."
            )
            warnings.warn(message, RuntimeWarning, stacklevel=2)

        self._cache = cache
        self._key = key
        self._timeout = timeout
        self._expire = expire
        self._tags = frozenset() if tags is None else frozenset(tags)

    @property
    @override
    def key(self) -> Any:
        return self._key

    @property
    @override
    def expire(self) -> float | None:
        return self._expire

    @property
    @override
    def timeout(self) -> float:
        return self._timeout

    @property
    @override
    def tags(self) -> frozenset[str]:
        return self._tags

    @property
    @override
    def locked(self) -> bool:
        return self.key in self._cache

    @context
    @override
    async def acquire(self) -> None:
        validate_installed("anyio", "Consider installing extra `asyncio`.")
        import anyio  # noqa: PLC0415

        try:
            with anyio.fail_after(self.timeout):
                while True:
                    added = await self._cache.aadd(
                        self.key, None, expire=self.expire, tags=self.tags, retry=True
                    )
                    if added:
                        break
                    await anyio.sleep(SPIN_LOCK_SLEEP)
        except TimeoutError as exc:
            raise te.TypedDiskcacheTimeoutError("lock acquire timeout") from exc

    @context
    @override
    async def release(self) -> None:
        await self._cache.adelete(self.key, retry=True)

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


class AsyncRLock(AsyncLock):
    """Re-entrant lock implementation using spin-lock algorithm.

    Assumes the key will not be evicted. Set the eviction policy to 'none' on
    the cache to guarantee the key is not evicted.

    Asynchronous version of [`SyncRLock`][typed_diskcache.SyncRLock].

    Args:
        cache: Cache to use for lock.
        key: Key for lock.
        timeout: Timeout for lock.
        expire: Expiration time for lock.
        tags: Tags for lock.

    Warns:
        RuntimeWarning:
            If the current Python interpreter is free-threading (without GIL),
            using [`AsyncRLock`][typed_diskcache.AsyncRLock] may lead to
            unexpected behavior. Consider using
            [`SyncRLock`][typed_diskcache.SyncRLock] instead in such cases.

    Examples:
        ```python
        import typed_diskcache


        async def main() -> None:
            cache = typed_diskcache.Cache()
            lock = typed_diskcache.AsyncLock(cache, "some-key")
            await lock.acquire()
            await lock.release()
            async with lock:
                pass
        ```
    """

    @context
    @override
    async def acquire(self) -> None:
        validate_installed("anyio", "Consider installing extra `asyncio`.")
        import anyio  # noqa: PLC0415

        pid = os.getpid()
        tid = threading.get_native_id()
        pid_tid = f"{pid}-{tid}"

        try:
            async with AsyncExitStack() as stack:
                stack.enter_context(anyio.fail_after(self.timeout))
                session = await stack.enter_async_context(
                    self._cache.conn.asession(stacklevel=4)
                )
                sub_stack = await stack.enter_async_context(AsyncExitStack())
                while True:
                    await sub_stack.enter_async_context(transact(session))
                    context = stack.enter_context(
                        self._cache.conn.enter_session(session)
                    )
                    container = await context.run(
                        self._cache.aget, self.key, default=("default", 0)
                    )
                    container_value = validate_lock_value(container.value)
                    if (
                        container.default
                        or pid_tid == container_value[0]
                        or container_value[1] <= 0
                    ):
                        value = 1 if container.default else container_value[1] + 1
                        logger.debug("acquired lock: %s, value: %d", pid_tid, value)
                        await context.run(
                            self._cache.aset,
                            self.key,
                            (pid_tid, value),
                            expire=self.expire,
                            tags=self.tags,
                        )
                        return
                    logger.debug(
                        "Invalid lock: expected: `%s`, value: `%s`",
                        pid_tid,
                        container_value,
                    )
                    await sub_stack.aclose()
                    await anyio.sleep(SPIN_LOCK_SLEEP)
        except TimeoutError as exc:
            raise te.TypedDiskcacheTimeoutError("lock acquire timeout") from exc

    @context
    @override
    async def release(self) -> None:
        """Release lock by decrementing count."""
        pid = os.getpid()
        tid = threading.get_native_id()
        pid_tid = f"{pid}-{tid}"

        async with AsyncExitStack() as stack:
            logger.debug("releasing lock: %s", pid_tid)
            session = await stack.enter_async_context(
                self._cache.conn.asession(stacklevel=4)
            )
            await stack.enter_async_context(transact(session))
            context = stack.enter_context(self._cache.conn.enter_session(session))
            container = await self._cache.aget(self.key, default=("default", 0))
            container_value = validate_lock_value(container.value)
            if (
                container.default
                or container_value[0] != pid_tid
                or container_value[1] <= 0
            ):
                logger.error(
                    "cannot release un-acquired lock, id: %s, default: %s, value: %s",
                    pid_tid,
                    container.default,
                    container_value,
                )
                raise te.TypedDiskcacheRuntimeError("cannot release un-acquired lock")
            await context.run(
                self._cache.aset,
                self.key,
                (container_value[0], container_value[1] - 1),
                expire=self.expire,
                tags=self.tags,
            )


def validate_lock_value(value: Any) -> tuple[str, int]:
    try:
        return _LOCK_VALUE_ADAPTER.validate_python(value)
    except ValueError as exc:
        raise te.TypedDiskcacheTypeError("invalid lock value") from exc
