from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, overload, runtime_checkable

from typing_extensions import TypeVar, Unpack

if TYPE_CHECKING:
    import warnings
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
    from pathlib import Path

    from typed_diskcache.core.types import (
        Container,
        FilterMethod,
        FilterMethodLiteral,
        QueueSide,
        QueueSideLiteral,
        SettingsKwargs,
        Stats,
    )
    from typed_diskcache.database import Connection
    from typed_diskcache.interface.disk import DiskProtocol
    from typed_diskcache.model import Settings

_AnyT = TypeVar("_AnyT", default=Any)


@runtime_checkable
class CacheProtocol(Protocol):
    """Disk and file backed cache.

    Args:
        directory: directory for cache
        disk_type: [`DiskProtocol`][typed_diskcache.interface.disk.DiskProtocol]
            class or callable
        disk_args: keyword arguments for `disk_type`
        **kwargs: additional keyword arguments for
            [`Settings`][typed_diskcache.model.Settings].
    """

    def __init__(
        self,
        directory: str | PathLike[str] | None = ...,
        disk_type: type[DiskProtocol] | Callable[..., DiskProtocol] | None = ...,
        disk_args: Mapping[str, Any] | None = ...,
        **kwargs: Unpack[SettingsKwargs],
    ) -> None: ...
    def __len__(self) -> int: ...
    def __setitem__(self, key: Any, value: Any) -> None: ...
    def __getitem__(self, key: Any) -> Any: ...
    def __contains__(self, key: Any) -> bool: ...
    def __delitem__(self, key: Any) -> None: ...
    def __iter__(self) -> Iterator[Any]: ...
    def __reversed__(self) -> Iterator[Any]: ...
    def __aiter__(self) -> AsyncIterator[Any]: ...
    def __getstate__(self) -> Mapping[str, Any]: ...
    def __setstate__(self, state: Mapping[str, Any]) -> None: ...

    @property
    def directory(self) -> Path:
        """Directory for cache."""
        ...

    @property
    def timeout(self) -> float:
        """Timeout for cache operations."""
        ...

    @property
    def conn(self) -> Connection:
        """Database connection."""
        ...

    @property
    def disk(self) -> DiskProtocol:
        """Disk object."""
        ...

    @property
    def settings(self) -> Settings:
        """Settings for cache."""
        ...

    @overload
    def get(
        self, key: Any, default: _AnyT, *, retry: bool = ...
    ) -> Container[Any | _AnyT]: ...
    @overload
    def get(
        self, key: Any, default: Any = ..., *, retry: bool = ...
    ) -> Container[Any]: ...
    def get(self, key: Any, default: Any = ..., *, retry: bool = ...) -> Container[Any]:
        """Retrieve value from cache.

        If `key` is missing, return container with `default`.

        Args:
            key: Key for item.
            default: Value to return if key is missing.
            retry: Retry if database timeout occurs.

        Returns:
            Container with cached value or default if key not found.
        """
        ...

    @overload
    async def aget(
        self, key: Any, default: _AnyT, *, retry: bool = ...
    ) -> Container[Any | _AnyT]: ...
    @overload
    async def aget(
        self, key: Any, default: Any = ..., *, retry: bool = ...
    ) -> Container[Any]: ...
    async def aget(
        self, key: Any, default: Any = ..., *, retry: bool = ...
    ) -> Container[Any]:
        """Asynchronously retrieve value from cache.

        If `key` is missing, return container with `default`.

        Args:
            key: Key for item.
            default: Value to return if key is missing.
            retry: Retry if database timeout occurs.

        Returns:
            Container with cached value or default if key not found.
        """
        ...

    def set(
        self,
        key: Any,
        value: Any,
        *,
        expire: float | None = ...,
        tags: str | Iterable[str] | None = ...,
        retry: bool = ...,
    ) -> bool:
        """Set `key` and `value` in cache.

        Args:
            key: Key for item.
            value: Value for item.
            expire: Seconds until item expires.
            tags: Tags to associate with key.
            retry: Retry if database timeout occurs.

        Returns:
            True if item was set.
        """
        ...

    async def aset(
        self,
        key: Any,
        value: Any,
        *,
        expire: float | None = ...,
        tags: str | Iterable[str] | None = ...,
        retry: bool = ...,
    ) -> bool:
        """Asynchronously set `key` and `value` in cache.

        Args:
            key: Key for item.
            value: Value for item.
            expire: Seconds until item expires.
            tags: Tags to associate with key.
            retry: Retry if database timeout occurs.

        Returns:
            True if item was set.
        """
        ...

    def delete(self, key: Any, *, retry: bool = ...) -> bool:
        """Delete corresponding item for `key` from cache.

        Missing keys are ignored.

        Args:
            key: Key matching item.
            retry: Retry if database timeout occurs.

        Returns:
            True if item was deleted.
        """
        ...

    async def adelete(self, key: Any, *, retry: bool = ...) -> bool:
        """Asynchronously delete corresponding item for `key` from cache.

        Missing keys are ignored.

        Args:
            key: Key matching item.
            retry: Retry if database timeout occurs.

        Returns:
            True if item was deleted.
        """
        ...

    def clear(self, *, retry: bool = ...) -> int:
        """Remove all items from cache.

        Removing items is iterative. Each iteration removes a subset of items.
        Concurrent writes may occur.

        If a [`TimeoutError`][] occurs, the first element of the exception's `args`
        attribute will be the number of items removed before the exception.

        Args:
            retry: Retry if database timeout occurs.

        Returns:
            Count of rows removed.
        """
        ...

    async def aclear(self, *, retry: bool = ...) -> int:
        """Asynchronously remove all items from cache.

        Removing items is iterative. Each iteration removes a subset of items.
        Concurrent writes may occur.

        If a [`TimeoutError`][] occurs, the first element of the exception's `args`
        attribute will be the number of items removed before the exception.

        Args:
            retry: Retry if database timeout occurs.

        Returns:
            Count of rows removed.
        """
        ...

    def stats(self, *, enable: bool = ..., reset: bool = ...) -> Stats:
        """Return cache statistics hits and misses.

        Args:
            enable: Enable collecting statistics.
            reset: Reset hits and misses to 0.

        Returns:
            (hits, misses)
        """
        ...

    async def astats(self, *, enable: bool = ..., reset: bool = ...) -> Stats:
        """Asynchronously return cache statistics hits and misses.

        Args:
            enable: Enable collecting statistics.
            reset: Reset hits and misses to 0.

        Returns:
            (hits, misses)
        """
        ...

    def volume(self) -> int:
        """Return estimated total size of cache on disk.

        Returns:
            Size in bytes.
        """
        ...

    async def avolume(self) -> int:
        """Asynchronously return estimated total size of cache on disk.

        Returns:
            Size in bytes.
        """
        ...

    def close(self) -> None:
        """Close database connection."""
        ...

    async def aclose(self) -> None:
        """Asynchronously close database connection."""
        ...

    def touch(self, key: Any, *, expire: float | None = ..., retry: bool = ...) -> bool:
        """Touch `key` in cache and update `expire` time.

        Args:
            key: Key for item.
            expire: Seconds until item expires. If None, no expiry.
            retry: Retry if database timeout occurs.

        Returns:
            True if key was touched.
        """
        ...

    async def atouch(
        self, key: Any, *, expire: float | None = ..., retry: bool = ...
    ) -> bool:
        """Asynchronously touch `key` in cache and update `expire` time.

        Args:
            key: Key for item.
            expire: Seconds until item expires. If None, no expiry.
            retry: Retry if database timeout occurs.

        Returns:
            True if key was touched.
        """
        ...

    def add(
        self,
        key: Any,
        value: Any,
        *,
        expire: float | None = ...,
        tags: str | Iterable[str] | None = ...,
        retry: bool = ...,
    ) -> bool:
        """Add `key` and `value` item to cache.

        Similar to `set`, but only add to cache if key not present.

        Operation is atomic. Only one concurrent add operation for a given key
        will succeed.

        Args:
            key: Key for item.
            value: Value for item.
            expire: Seconds until the key expires. If None, no expiry.
            tags: Tags to associate with key.
            retry: Retry if database timeout occurs.

        Returns:
            True if item was added.
        """
        ...

    async def aadd(
        self,
        key: Any,
        value: Any,
        *,
        expire: float | None = ...,
        tags: str | Iterable[str] | None = ...,
        retry: bool = ...,
    ) -> bool:
        """Asynchronously add `key` and `value` item to cache.

        Similar to `set`, but only add to cache if key not present.

        Operation is atomic. Only one concurrent add operation for a given key
        will succeed.

        Args:
            key: Key for item.
            value: Value for item.
            expire: Seconds until the key expires. If None, no expiry.
            tags: Tags to associate with key.
            retry: Retry if database timeout occurs.

        Returns:
            True if item was added.
        """
        ...

    @overload
    def pop(
        self, key: Any, default: _AnyT, *, retry: bool = ...
    ) -> Container[Any | _AnyT]: ...
    @overload
    def pop(
        self, key: Any, default: Any = ..., *, retry: bool = ...
    ) -> Container[Any]: ...
    def pop(self, key: Any, default: Any = ..., *, retry: bool = ...) -> Container[Any]:
        """Remove corresponding item for `key` from cache and return value.

        If `key` is missing, return `default`.

        Operation is atomic. Concurrent operations will be serialized.

        Args:
            key: Key for item.
            default: Value to return if key is missing.
            retry: Retry if database timeout occurs.

        Returns:
            Container with cached value or default if key not found.
        """
        ...

    @overload
    async def apop(
        self, key: Any, default: _AnyT, *, retry: bool = ...
    ) -> Container[Any | _AnyT]: ...
    @overload
    async def apop(
        self, key: Any, default: Any = ..., *, retry: bool = ...
    ) -> Container[Any]: ...
    async def apop(
        self, key: Any, default: Any = ..., *, retry: bool = ...
    ) -> Container[Any]:
        """
        Asynchronously remove corresponding item for `key` from cache and return value.

        If `key` is missing, return `default`.

        Operation is atomic. Concurrent operations will be serialized.

        Args:
            key: Key for item.
            default: Value to return if key is missing.
            retry: Retry if database timeout occurs.

        Returns:
            Container with cached value or default if key not found.
        """
        ...

    def filter(
        self,
        tags: str | Iterable[str],
        *,
        method: FilterMethodLiteral | FilterMethod = ...,
    ) -> Generator[Any, None, None]:
        """Filter by tags.

        Args:
            tags: Tags to filter by.
            method: 'and' or 'or' filter method.

        Yields:
            Key of item matching tags.
        """
        ...

    async def afilter(
        self,
        tags: str | Iterable[str],
        *,
        method: FilterMethodLiteral | FilterMethod = ...,
    ) -> AsyncGenerator[Any, None]:
        """Asynchronously filter by tags.

        Args:
            tags: Tags to filter by.
            method: 'and' or 'or' filter method.

        Yields:
            Key of item matching tags.
        """
        ...

    def incr(
        self,
        key: Any,
        delta: int = ...,
        default: int | None = ...,
        *,
        retry: bool = ...,
    ) -> int:
        """Increment value by delta for item with key.

        If key is missing and default is None then raise [`KeyError`][]. Else if key
        is missing and default is not None then use default for value.

        Operation is atomic. All concurrent increment operations will be
        counted individually.

        Assumes value may be stored in a SQLite column. Most builds that target
        machines with 64-bit pointer widths will support 64-bit signed integers.

        Args:
            key: Key for item.
            delta: Amount to increment.
            default: Value if key is missing.
            retry: Retry if database timeout occurs.

        Returns:
            Incremented value or default if key not found.
        """
        ...

    async def aincr(
        self,
        key: Any,
        delta: int = ...,
        default: int | None = ...,
        *,
        retry: bool = ...,
    ) -> int:
        """Async increment value by delta for item with key.

        If key is missing and default is None then raise [`KeyError`]. Else if key
        is missing and default is not None then use default for value.

        Operation is atomic. All concurrent increment operations will be
        counted individually.

        Assumes value may be stored in a SQLite column. Most builds that target
        machines with 64-bit pointer widths will support 64-bit signed integers.

        Args:
            key: Key for item.
            delta: Amount to increment.
            default: Value if key is missing.
            retry: Retry if database timeout occurs.

        Returns:
            Incremented value or default if key not found.
        """
        ...

    def decr(
        self,
        key: Any,
        delta: int = ...,
        default: int | None = ...,
        *,
        retry: bool = ...,
    ) -> int:
        """Decrement value by delta for item with key.

        If key is missing and default is None then raise [`KeyError`][]. Else if key
        is missing and default is not None then use default for value.

        Operation is atomic. All concurrent decrement operations will be
        counted individually.

        Unlike Memcached, negative values are supported. Value may be
        decremented below zero.

        Assumes value may be stored in a SQLite column. Most builds that target
        machines with 64-bit pointer widths will support 64-bit signed integers.

        Args:
            key: Key for item.
            delta: Amount to decrement.
            default: Value if key is missing.
            retry: Retry if database timeout occurs.

        Returns:
            Decremented value or default if key not found.
        """
        ...

    async def adecr(
        self,
        key: Any,
        delta: int = ...,
        default: int | None = ...,
        *,
        retry: bool = ...,
    ) -> int:
        """Async decrement value by delta for item with key.

        If key is missing and default is None then raise [`KeyError`][]. Else if key
        is missing and default is not None then use default for value.

        Operation is atomic. All concurrent decrement operations will be
        counted individually.

        Unlike Memcached, negative values are supported. Value may be
        decremented below zero.

        Assumes value may be stored in a SQLite column. Most builds that target
        machines with 64-bit pointer widths will support 64-bit signed integers.

        Args:
            key: Key for item.
            delta: Amount to decrement.
            default: Value if key is missing.
            retry: Retry if database timeout occurs.

        Returns:
            Decremented value or default if key not found.
        """
        ...

    def evict(
        self,
        tags: str | Iterable[str],
        *,
        method: FilterMethodLiteral | FilterMethod = ...,
        retry: bool = False,
    ) -> int:
        """Remove items with matching `tag` from cache.

        Removing items is an iterative process. In each iteration, a subset of
        items is removed. Concurrent writes may occur between iterations.

        If a [`TimeoutError`][] occurs, the first element of the exception's
        `args` attribute will be the number of items removed before the
        exception occurred.

        Args:
            tags: Tags identifying items.
            method: 'and' or 'or' filter method.
            retry: Retry if database timeout occurs.

        Returns:
            Count of rows removed.
        """
        ...

    async def aevict(
        self,
        tags: str | Iterable[str],
        *,
        method: FilterMethodLiteral | FilterMethod = ...,
        retry: bool = False,
    ) -> int:
        """Async remove items with matching `tag` from cache.

        Removing items is an iterative process. In each iteration, a subset of
        items is removed. Concurrent writes may occur between iterations.

        If a [`TimeoutError`][] occurs, the first element of the exception's
        `args` attribute will be the number of items removed before the
        exception occurred.

        Args:
            tags: Tags identifying items.
            method: 'and' or 'or' filter method.
            retry: Retry if database timeout occurs.

        Returns:
            Count of rows removed.
        """
        ...

    def expire(self, now: float | None = ..., *, retry: bool = ...) -> int:
        """Remove expired items from cache.

        Removing items is an iterative process. In each iteration, a subset of
        items is removed. Concurrent writes may occur between iterations.

        If a [`TimeoutError`][] occurs, the first element of the exception's
        `args` attribute will be the number of items removed before the
        exception occurred.

        Args:
            now: Current time. If None, use [`time.time()`][time.time].
            retry: Retry if database timeout occurs.

        Returns:
            Count of items removed.
        """
        ...

    async def aexpire(self, now: float | None = ..., *, retry: bool = ...) -> int:
        """Async remove expired items from cache.

        Removing items is an iterative process. In each iteration, a subset of
        items is removed. Concurrent writes may occur between iterations.

        If a [`TimeoutError`][] occurs, the first element of the exception's
        `args` attribute will be the number of items removed before the
        exception occurred.

        Args:
            now: Current time. If None, use [`time.time()`][time.time].
            retry: Retry if database timeout occurs.

        Returns:
            Count of items removed.
        """
        ...

    def cull(self, *, retry: bool = ...) -> int:
        """Cull items from cache until volume is less than size limit.

        Removing items is an iterative process. In each iteration, a subset of
        items is removed. Concurrent writes may occur between iterations.

        If a [`TimeoutError`][] occurs, the first element of the exception's
        `args` attribute will be the number of items removed before the
        exception occurred.

        Args:
            retry: Retry if database timeout occurs.

        Returns:
            Count of items removed.
        """
        ...

    async def acull(self, *, retry: bool = ...) -> int:
        """Async cull items from cache until volume is less than size limit.

        Removing items is an iterative process. In each iteration, a subset of
        items is removed. Concurrent writes may occur between iterations.

        If a [`TimeoutError`][] occurs, the first element of the exception's
        `args` attribute will be the number of items removed before the
        exception occurred.

        Args:
            retry: Retry if database timeout occurs.

        Returns:
            Count of items removed.
        """
        ...

    def push(  # noqa: PLR0913
        self,
        value: Any,
        *,
        prefix: str | None = ...,
        side: QueueSideLiteral | QueueSide = ...,
        expire: float | None = ...,
        tags: str | Iterable[str] | None = ...,
        retry: bool = ...,
    ) -> Any:
        """Push `value` onto `side` of queue identified by `prefix` in cache.

        When prefix is None, integer keys are used. Otherwise, string keys are used.

        Operation is atomic. Concurrent operations will be serialized.

        See also [`pull`][typed_diskcache.interface.CacheProtocol.pull].

        Args:
            value: Value for item.
            prefix: Key prefix. If None, key is integer.
            side: Either 'back' or 'front'.
            expire: Seconds until the key expires. If None, no expiry.
            tags: Tags to associate with key.
            retry: Retry if database timeout occurs.

        Returns:
            Key of the pushed item.

        Examples:
            ```python
            import typed_diskcache


            def main() -> None:
                cache = typed_diskcache.Cache()
                print(cache.push("first value"))
                # 500000000000000
                print(cache.get(500000000000000))
                # first value
                print(cache.push("second value"))
                # 500000000000001
                print(cache.push("third value", side="front"))
                # 499999999999999
                print(cache.push(1234, prefix="userids"))
                # userids-500000000000000
            ```
        """
        ...

    async def apush(  # noqa: PLR0913
        self,
        value: Any,
        *,
        prefix: str | None = ...,
        side: QueueSideLiteral | QueueSide = ...,
        expire: float | None = ...,
        tags: str | Iterable[str] | None = ...,
        retry: bool = ...,
    ) -> Any:
        """Async push `value` onto `side` of queue identified by `prefix` in cache.

        When prefix is None, integer keys are used. Otherwise, string keys are used.

        Operation is atomic. Concurrent operations will be serialized.

        See also [`apull`][typed_diskcache.interface.CacheProtocol.apull].

        Args:
            value: Value for item.
            prefix: Key prefix. If None, key is integer.
            side: Either 'back' or 'front'.
            expire: Seconds until the key expires. If None, no expiry.
            tags: Tags to associate with key.
            retry: Retry if database timeout occurs.

        Returns:
            Key of the pushed item.

        Examples:
            ```python
            import typed_diskcache


            async def main() -> None:
                cache = typed_diskcache.Cache()
                print(await cache.apush("first value"))
                # 500000000000000
                print(await cache.aget(500000000000000))
                # first value
                print(await cache.apush("second value"))
                # 500000000000001
                print(await cache.apush("third value", side="front"))
                # 499999999999999
                print(await cache.apush(1234, prefix="userids"))
                # userids-500000000000000
            ```
        """
        ...

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
    def pull(
        self,
        *,
        prefix: str | None = ...,
        default: tuple[Any, Any] | None = ...,
        side: QueueSideLiteral | QueueSide = ...,
        retry: bool = ...,
    ) -> Container[Any]:
        """Pull key and value item pair from `side` of queue in cache.

        When prefix is None, integer keys are used. Otherwise, string keys are used.

        If queue is empty, return default.

        Operation is atomic. Concurrent operations will be serialized.

        See also [`push`][typed_diskcache.interface.CacheProtocol.push]
        and [`get`][typed_diskcache.interface.CacheProtocol.get].

        Args:
            prefix: Key prefix. If None, key is integer.
            default: Value to return if key is missing.
            side: Either 'back' or 'front'.
            retry: Retry if database timeout occurs.

        Returns:
            Container with cached value or default if queue is empty.

        Examples:
            ```python
            import typed_diskcache


            def main() -> None:
                cache = typed_diskcache.Cache()
                print(cache.pull())
                # Container(default=True, expire_time=None, tags=None)
                for letter in "abc":
                    print(cache.push(letter))
                # 500000000000000
                # 500000000000001
                # 500000000000002
                container = cache.pull()
                print(container.key)
                # 500000000000000
                print(container.value)
                # a
                container = cache.pull(side="back")
                print(container.value)
                # c
                print(cache.push(1234, prefix="userids"))
                # userids-500000000000000
                container = cache.pull(prefix="userids")
                print(container.value)
                # 1234
            ```
        """
        ...

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
    async def apull(
        self,
        *,
        prefix: str | None = ...,
        default: tuple[Any, Any] | None = ...,
        side: QueueSideLiteral | QueueSide = ...,
        retry: bool = ...,
    ) -> Container[Any]:
        """Async pull key and value item pair from `side` of queue in cache.

        When prefix is None, integer keys are used. Otherwise, string keys are used.

        If queue is empty, return default.

        Operation is atomic. Concurrent operations will be serialized.

        See also [`apush`][typed_diskcache.interface.CacheProtocol.apush]
        and [`aget`][typed_diskcache.interface.CacheProtocol.aget].

        Args:
            prefix: Key prefix. If None, key is integer.
            default: Value to return if key is missing.
            side: Either 'back' or 'front'.
            retry: Retry if database timeout occurs.

        Returns:
            Container with cached value or default if queue is empty.

        Examples:
            ```python
            import typed_diskcache


            async def main() -> None:
                cache = typed_diskcache.Cache()
                print(await cache.apull())
                # Container(default=True, expire_time=None, tags=None)
                for letter in "abc":
                    print(await cache.apush(letter))
                # 500000000000000
                # 500000000000001
                # 500000000000002
                container = await cache.apull()
                print(container.key)
                # 500000000000000
                print(container.value)
                # a
                container = await cache.apull(side="back")
                print(container.value)
                # c
                print(await cache.apush(1234, prefix="userids"))
                # userids-500000000000000
                container = await cache.apull(prefix="userids")
                print(container.value)
                # 1234
            ```
        """
        ...

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
    def peek(
        self,
        *,
        prefix: str | None = ...,
        default: tuple[Any, Any] | None = ...,
        side: QueueSideLiteral | QueueSide = ...,
        retry: bool = ...,
    ) -> Container[Any]:
        """Peek at key and value item pair from `side` of queue in cache.

        When prefix is None, integer keys are used. Otherwise, string keys are used.

        If queue is empty, return default.

        Expired items are deleted from cache. Operation is atomic. Concurrent
        operations will be serialized.

        See also [`pull`][typed_diskcache.interface.CacheProtocol.pull]
        and [`push`][typed_diskcache.interface.CacheProtocol.push].

        Args:
            prefix: Key prefix. If None, key is integer.
            default: Value to return if key is missing.
            side: Either 'back' or 'front'.
            retry: Retry if database timeout occurs.

        Returns:
            Container with cached value or default if queue is empty.

        Examples:
            ```python
            import typed_diskcache


            def main() -> None:
                cache = typed_diskcache.Cache()
                for letter in "abc":
                    print(cache.push(letter))
                # 500000000000000
                # 500000000000001
                # 500000000000002
                container = cache.peek()
                print(container.key)
                # 500000000000002
                print(container.value)
                # c
                container = cache.peek(side="front")
                print(container.key)
                # 500000000000000
                print(container.value)
                # a
            ```
        """
        ...

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
    async def apeek(
        self,
        *,
        prefix: str | None = ...,
        default: tuple[Any, Any] | None = ...,
        side: QueueSideLiteral | QueueSide = ...,
        retry: bool = ...,
    ) -> Container[Any]:
        """Async peek at key and value item pair from `side` of queue in cache.

        When prefix is None, integer keys are used. Otherwise, string keys are used.

        If queue is empty, return default.

        Expired items are deleted from cache. Operation is atomic. Concurrent
        operations will be serialized.

        See also [`apull`][typed_diskcache.interface.CacheProtocol.apull]
        and [`apush`][typed_diskcache.interface.CacheProtocol.apush].

        Args:
            prefix: Key prefix. If None, key is integer.
            default: Value to return if key is missing.
            side: Either 'back' or 'front'.
            retry: Retry if database timeout occurs.

        Returns:
            Container with cached value or default if queue is empty.

        Examples:
            ```python
            import typed_diskcache


            async def main() -> None:
                cache = typed_diskcache.Cache()
                for letter in "abc":
                    print(await cache.apush(letter))
                # 500000000000000
                # 500000000000001
                # 500000000000002
                container = await cache.apeek()
                print(container.key)
                # 500000000000002
                print(container.value)
                # c
                container = await cache.apeek(side="front")
                print(container.key)
                # 500000000000000
                print(container.value)
                # a
            ```
        """
        ...

    def peekitem(self, *, last: bool = ..., retry: bool = ...) -> Container[Any]:
        """Peek at key and value item pair in cache based on iteration order.

        Expired items are deleted from cache. Operation is atomic. Concurrent
        operations will be serialized.

        Args:
            last: Last item in iteration order.
            retry: Retry if database timeout occurs.

        Returns:
            Container with cached value.

        Examples:
            ```python
            import typed_diskcache


            def main() -> None:
                cache = typed_diskcache.Cache()
                for num, letter in enumerate("abc"):
                    cache[letter] = num
                container = cache.peekitem()
                print(container.key, container.value)
                # ('c', 2)
                container = cache.peekitem(last=False)
                print(container.key, container.value)
                # ('a', 0)
            ```
        """
        ...

    async def apeekitem(self, *, last: bool = ..., retry: bool = ...) -> Container[Any]:
        """Async peek at key and value item pair in cache based on iteration order.

        Expired items are deleted from cache. Operation is atomic. Concurrent
        operations will be serialized.

        Args:
            last: Last item in iteration order.
            retry: Retry if database timeout occurs.

        Returns:
            Container with cached value.

        Examples:
            ```python
            import typed_diskcache


            async def main() -> None:
                cache = typed_diskcache.Cache()
                for num, letter in enumerate("abc"):
                    cache[letter] = num
                container = await cache.apeekitem()
                print(container.key, container.value)
                # ('c', 2)
                container = await cache.apeekitem(last=False)
                print(container.key, container.value)
                # ('a', 0)
            ```
        """
        ...

    def check(
        self, *, fix: bool = ..., retry: bool = ...
    ) -> list[warnings.WarningMessage]:
        """Check database and file system consistency.

        Intended for use in testing and post-mortem error analysis.

        While checking the Cache table for consistency, a writer lock is held
        on the database. The lock blocks other cache clients from writing to
        the database. For caches with many file references, the lock may be
        held for a long time. For example, local benchmarking shows that a
        cache with 1,000 file references takes ~60ms to check.

        Args:
            fix: Correct inconsistencies.
            retry: Retry if database timeout occurs.

        Returns:
            List of warnings.
        """
        ...

    async def acheck(
        self, *, fix: bool = ..., retry: bool = ...
    ) -> list[warnings.WarningMessage]:
        """Async check database and file system consistency.

        Intended for use in testing and post-mortem error analysis.

        While checking the Cache table for consistency, a writer lock is held
        on the database. The lock blocks other cache clients from writing to
        the database. For caches with many file references, the lock may be
        held for a long time. For example, local benchmarking shows that a
        cache with 1,000 file references takes ~60ms to check.

        Args:
            fix: Correct inconsistencies.
            retry: Retry if database timeout occurs.

        Returns:
            List of warnings.
        """
        ...
        ...

    def iterkeys(self, *, reverse: bool = ...) -> Generator[Any, None, None]:
        """Iterate Cache keys in database sort order.

        Args:
            reverse: Reverse sort order.

        Yields:
            Key of item.

        Examples:
            ```python
            import typed_diskcache


            def main() -> None:
                cache = typed_diskcache.Cache()
                for key in [4, 1, 3, 0, 2]:
                    cache[key] = key
                print(list(cache.iterkeys()))
                # [0, 1, 2, 3, 4]
                print(list(cache.iterkeys(reverse=True)))
                # [4, 3, 2, 1, 0]
            ```
        """
        ...

    async def aiterkeys(self, *, reverse: bool = ...) -> AsyncGenerator[Any, None]:
        """Async iterate Cache keys in database sort order.

        Args:
            reverse: Reverse sort order.

        Yields:
            Key of item.

        Examples:
            ```python
            import typed_diskcache


            async def main() -> None:
                cache = typed_diskcache.Cache()
                for key in [4, 1, 3, 0, 2]:
                    cache[key] = key
                print([x async for x in cache.aiterkeys()])
                # [0, 1, 2, 3, 4]
                print([x async for x in cache.aiterkeys(reverse=True)])
                # [4, 3, 2, 1, 0]
            ```
        """
        ...

    def update_settings(self, settings: Settings) -> None:
        """Update cache settings.

        Args:
            settings: New settings.
        """
        ...

    async def aupdate_settings(self, settings: Settings) -> None:
        """Async update cache settings.

        Asynchronous version of
        [`update_settings`][typed_diskcache.interface.CacheProtocol.update_settings].

        Args:
            settings: New settings.
        """
        ...
