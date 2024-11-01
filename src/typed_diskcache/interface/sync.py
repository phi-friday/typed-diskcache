# pyright: reportReturnType=false
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Iterable
    from types import TracebackType

    from typed_diskcache.interface.cache import CacheProtocol

__all__ = [
    "SyncLockProtocol",
    "SyncSemaphoreProtocol",
    "AsyncLockProtocol",
    "AsyncSemaphoreProtocol",
]


@runtime_checkable
class SyncLockProtocol(Protocol):
    """Recipe for cross-process and cross-thread lock.

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

    def __init__(
        self,
        cache: CacheProtocol,
        key: Any,
        *,
        timeout: float = ...,
        expire: float | None = ...,
        tags: str | Iterable[str] | None = ...,
    ) -> None: ...
    @property
    def key(self) -> Any:
        """Key for lock."""

    @property
    def timeout(self) -> float:
        """Timeout for lock."""

    @property
    def expire(self) -> float | None:
        """Expiration time for lock."""

    @property
    def tags(self) -> frozenset[str]:
        """Tags for lock."""

    @property
    def locked(self) -> bool:
        """Return true if the lock is acquired."""

    def acquire(self) -> None:
        """Acquire lock using spin-lock algorithm."""

    def release(self) -> None:
        """Release lock by deleting key."""

    def __enter__(self) -> None: ...

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_value: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None: ...


@runtime_checkable
class SyncSemaphoreProtocol(Protocol):
    """Recipe for cross-process and cross-thread bounded semaphore.

    Assumes the key will not be evicted. Set the eviction policy to 'none' on
    the cache to guarantee the key is not evicted.

    Args:
        cache: Cache to use for semaphore.
        key: Key for semaphore.
        value: Value for semaphore.
        timeout: Timeout for semaphore.
        expire: Expiration time for semaphore.
        tags: Tags for semaphore.

    Examples:
        ```python
        import typed_diskcache


        def main() -> None:
            cache = typed_diskcache.Cache()
            semaphore = typed_diskcache.SyncSemaphore(cache, "some-key", value=2)
            semaphore.acquire()
            semaphore.acquire()
            semaphore.release()
            with semaphore:
                pass
        ```
    """

    def __init__(  # noqa: PLR0913
        self,
        cache: CacheProtocol,
        key: Any,
        value: int = ...,
        *,
        timeout: float = ...,
        expire: float | None = ...,
        tags: str | Iterable[str] | None = ...,
    ) -> None: ...
    @property
    def key(self) -> Any:
        """Key for semaphore."""

    @property
    def value(self) -> int:
        """Value for semaphore."""

    @property
    def timeout(self) -> float:
        """Timeout for semaphore."""

    @property
    def expire(self) -> float | None:
        """Expiration time for semaphore."""

    @property
    def tags(self) -> frozenset[str]:
        """Tags for semaphore."""

    def acquire(self) -> None:
        """Acquire semaphore by decrementing value using spin-lock algorithm."""

    def release(self) -> None:
        """Release semaphore by incrementing value."""

    def __enter__(self) -> None: ...

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_value: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None: ...


@runtime_checkable
class AsyncLockProtocol(Protocol):
    """Recipe for cross-process and cross-thread lock.

    Assumes the key will not be evicted. Set the eviction policy to 'none' on
    the cache to guarantee the key is not evicted.

    Asynchronous version of
    [`SyncLockProtocol`][typed_diskcache.interface.sync.SyncLockProtocol].

    Args:
        cache: Cache to use for lock.
        key: Key for lock.
        timeout: Timeout for lock.
        expire: Expiration time for lock.
        tags: Tags for lock.

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

    def __init__(
        self,
        cache: CacheProtocol,
        key: Any,
        *,
        timeout: float = ...,
        expire: float | None = ...,
        tags: str | Iterable[str] | None = ...,
    ) -> None: ...
    @property
    def key(self) -> Any:
        """Key for lock."""

    @property
    def timeout(self) -> float:
        """Timeout for lock."""

    @property
    def expire(self) -> float | None:
        """Expiration time for lock."""

    @property
    def tags(self) -> frozenset[str]:
        """Tags for lock."""

    @property
    def locked(self) -> bool:
        """Return true if the lock is acquired."""

    async def acquire(self) -> None:
        """Acquire lock using spin-lock algorithm."""

    async def release(self) -> None:
        """Release lock by deleting key."""

    async def __aenter__(self) -> None: ...

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_value: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None: ...


@runtime_checkable
class AsyncSemaphoreProtocol(Protocol):
    """Recipe for cross-process and cross-thread bounded semaphore.

    Assumes the key will not be evicted. Set the eviction policy to 'none' on
    the cache to guarantee the key is not evicted.

    Asynchronous version of
    [`SyncSemaphoreProtocol`][typed_diskcache.interface.sync.SyncSemaphoreProtocol].

    Args:
        cache: Cache to use for semaphore.
        key: Key for semaphore.
        value: Value for semaphore.
        timeout: Timeout for semaphore.
        expire: Expiration time for semaphore.
        tags: Tags for semaphore.

    Examples:
        ```python
        import typed_diskcache


        async def main() -> None:
                cache = typed_diskcache.Cache()
                semaphore = typed_diskcache.AsyncSemaphore(cache, "some-key", value=2)
                await semaphore.acquire()
                await semaphore.acquire()
                await semaphore.release()
                async with semaphore:
                    pass
        ```
    """

    def __init__(  # noqa: PLR0913
        self,
        cache: CacheProtocol,
        key: Any,
        value: int = ...,
        *,
        timeout: float = ...,
        expire: float | None = ...,
        tags: str | Iterable[str] | None = ...,
    ) -> None: ...
    @property
    def key(self) -> Any:
        """Key for semaphore."""

    @property
    def value(self) -> int:
        """Value for semaphore."""

    @property
    def timeout(self) -> float:
        """Timeout for semaphore."""

    @property
    def expire(self) -> float | None:
        """Expiration time for semaphore."""

    @property
    def tags(self) -> frozenset[str]:
        """Tags for semaphore."""

    async def acquire(self) -> None:
        """Acquire semaphore by decrementing value using spin-lock algorithm."""

    async def release(self) -> None:
        """Release semaphore by incrementing value."""

    async def __aenter__(self) -> None: ...

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_value: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None: ...
