from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, Protocol, overload, runtime_checkable

from typing_extensions import TypeVar

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
        QueueSide,
        QueueSideLiteral,
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
        disk_type: `DiskProtocol` class or callable
        disk_args: keyword arguments for `disk_type`
        kwargs: additional keyword arguments
            for `DiskProtocol`, `CacheProtocol` and `Settings`
    """

    def __init__(
        self,
        directory: str | PathLike[str] | None = ...,
        disk_type: type[DiskProtocol] | Callable[..., DiskProtocol] | None = ...,
        disk_args: Mapping[str, Any] | None = ...,
        **kwargs: Any,
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
        """Retrieve value from cache. If `key` is missing, return `default`.

        Args:
            key: key for item
            default: value to return if key is missing
            retry: retry if database timeout occurs

        Returns:
            value for item or default if key not found
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
        """Retrieve value from cache. If `key` is missing, return `default`.

        Asynchronous version of `get`.

        Args:
            key: key for item
            default: value to return if key is missing
            retry: retry if database timeout occurs

        Returns:
            value for item or default if key not found
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
        """Set `key` and `value` item in cache.

        Args:
            key: key for item
            value: value for item
            expire: seconds until item expires
            tags: texts to associate with key
            retry: retry if database timeout occurs

        Returns:
            True if item was set
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
        """Set `key` and `value` item in cache.

        Asynchronous version of `set`.

        Args:
            key: key for item
            value: value for item
            expire: seconds until item expires
            tags: texts to associate with key
            retry: retry if database timeout occurs

        Returns:
            True if item was set
        """
        ...

    def delete(self, key: Any, *, retry: bool = ...) -> bool:
        """Delete corresponding item for `key` from cache.

        Missing keys are ignored.

        Args:
            key: key matching item
            retry: retry if database timeout occurs

        Returns:
            True if item was deleted
        """
        ...

    async def adelete(self, key: Any, *, retry: bool = ...) -> bool:
        """Delete corresponding item for `key` from cache.

        Asynchronous version of `delete`.

        Missing keys are ignored.

        Args:
            key: key matching item
            retry: retry if database timeout occurs

        Returns:
            True if item was deleted
        """
        ...

    def clear(self, *, retry: bool = ...) -> int:
        """Remove all items from cache.

        Removing items is an iterative process. In each iteration, a subset of
        items is removed. Concurrent writes may occur between iterations.

        If a :exc:`Timeout` occurs, the first element of the exception's
        `args` attribute will be the number of items removed before the
        exception occurred.

        Args:
            retry: retry if database timeout occurs

        Returns:
            count of rows removed
        """
        ...

    async def aclear(self, *, retry: bool = ...) -> int:
        """Remove all items from cache.

        Asynchronous version of `clear`.

        Removing items is an iterative process. In each iteration, a subset of
        items is removed. Concurrent writes may occur between iterations.

        If a :exc:`Timeout` occurs, the first element of the exception's
        `args` attribute will be the number of items removed before the
        exception occurred.

        Args:
            retry: retry if database timeout occurs

        Returns:
            count of rows removed
        """
        ...

    def stats(self, *, enable: bool = ..., reset: bool = ...) -> Stats:
        """Return cache statistics hits and misses.

        Args:
            enable: enable collecting statistics
            reset: reset hits and misses to 0

        Returns:
            (hits, misses)
        """
        ...

    async def astats(self, *, enable: bool = ..., reset: bool = ...) -> Stats:
        """Return cache statistics hits and misses.

        Asynchronous version of `stats`.

        Args:
            enable: enable collecting statistics
            reset: reset hits and misses to 0

        Returns:
            (hits, misses)
        """
        ...

    def volume(self) -> int:
        """Return estimated total size of cache on disk.

        Returns:
            size in bytes
        """
        ...

    async def avolume(self) -> int:
        """Return estimated total size of cache on disk.

        Asynchronous version of `volume`.

        Returns:
            size in bytes
        """
        ...

    def close(self) -> None:
        """Close database connection."""
        ...

    async def aclose(self) -> None:
        """Close database connection."""
        ...

    def touch(self, key: Any, *, expire: float | None = ..., retry: bool = ...) -> bool:
        """Touch `key` in cache and update `expire` time.

        Args:
            key: key for item
            expire: seconds until item expires. If None, no expiry.
            retry: retry if database timeout occurs

        Returns:
            True if key was touched
        """
        ...

    async def atouch(
        self, key: Any, *, expire: float | None = ..., retry: bool = ...
    ) -> bool:
        """Touch `key` in cache and update `expire` time.

        Asynchronous version of `touch`.

        Args:
            key: key for item
            expire: seconds until item expires. If None, no expiry.
            retry: retry if database timeout occurs

        Returns:
            True if key was touched
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
            key: key for item
            value: value for item
            expire: seconds until the key expires. If None, no expiry.
            tags: texts to associate with key
            retry: retry if database timeout occurs

        Returns:
            True if item was added
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
        """Add `key` and `value` item to cache.

        Asynchronous version of `add`.

        Similar to `set`, but only add to cache if key not present.

        Operation is atomic. Only one concurrent add operation for a given key
        will succeed.

        Args:
            key: key for item
            value: value for item
            expire: seconds until the key expires. If None, no expiry.
            tags: texts to associate with key
            retry: retry if database timeout occurs

        Returns:
            True if item was added
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
            key: key for item
            default: value to return if key is missing
            retry: retry if database timeout occurs

        Returns:
            value for item or default if key not found
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
        """Remove corresponding item for `key` from cache and return value.

        Asynchronous version of `pop`.

        If `key` is missing, return `default`.

        Operation is atomic. Concurrent operations will be serialized.

        Args:
            key: key for item
            default: value to return if key is missing
            retry: retry if database timeout occurs

        Returns:
            value for item or default if key not found
        """
        ...

    def filter(
        self,
        tags: str | Iterable[str],
        *,
        method: Literal["and", "or"] | FilterMethod = ...,
    ) -> Generator[Any, None, None]:
        """Filter by tags.

        Args:
            tags: tags to filter by
            method: 'and' or 'or' filter method

        Yields:
            key of item matching tags
        """
        ...

    async def afilter(
        self,
        tags: str | Iterable[str],
        *,
        method: Literal["and", "or"] | FilterMethod = ...,
    ) -> AsyncGenerator[Any, None]:
        """Filter by tags.

        Asynchronous version of `filter`.

        Args:
            tags: tags to filter by
            method: 'and' or 'or' filter method

        Yields:
            key of item matching tags
        """
        ...

    def incr(
        self,
        key: Any,
        delta: int = ...,
        default: int | None = ...,
        *,
        retry: bool = ...,
    ) -> int | None:
        """Increment value by delta for item with key.

        If key is missing and default is None then raise KeyError. Else if key
        is missing and default is not None then use default for value.

        Operation is atomic. All concurrent increment operations will be
        counted individually.

        Assumes value may be stored in a SQLite column. Most builds that target
        machines with 64-bit pointer widths will support 64-bit signed
        integers.

        Args:
            key: key for item
            delta: amount to increment
            default: value if key is missing
            retry: retry if database timeout occurs

        Returns:
            new value for item
        """
        ...

    async def aincr(
        self,
        key: Any,
        delta: int = ...,
        default: int | None = ...,
        *,
        retry: bool = ...,
    ) -> int | None:
        """Increment value by delta for item with key.

        Asynchronous version of `incr`.

        If key is missing and default is None then raise KeyError. Else if key
        is missing and default is not None then use default for value.

        Operation is atomic. All concurrent increment operations will be
        counted individually.

        Assumes value may be stored in a SQLite column. Most builds that target
        machines with 64-bit pointer widths will support 64-bit signed
        integers.

        Args:
            key: key for item
            delta: amount to increment
            default: value if key is missing
            retry: retry if database timeout occurs

        Returns:
            new value for item
        """
        ...

    def decr(
        self,
        key: Any,
        delta: int = ...,
        default: int | None = ...,
        *,
        retry: bool = ...,
    ) -> int | None:
        """Decrement value by delta for item with key.

        If key is missing and default is None then raise KeyError. Else if key
        is missing and default is not None then use default for value.

        Operation is atomic. All concurrent decrement operations will be
        counted individually.

        Unlike Memcached, negative values are supported. Value may be
        decremented below zero.

        Assumes value may be stored in a SQLite column. Most builds that target
        machines with 64-bit pointer widths will support 64-bit signed
        integers.

        Args:
            key: key for item
            delta: amount to decrement
            default: value if key is missing
            retry: retry if database timeout occurs

        Returns:
            new value for item
        """
        ...

    async def adecr(
        self,
        key: Any,
        delta: int = ...,
        default: int | None = ...,
        *,
        retry: bool = ...,
    ) -> int | None:
        """Decrement value by delta for item with key.

        Asynchronous version of `decr`.

        If key is missing and default is None then raise KeyError. Else if key
        is missing and default is not None then use default for value.

        Operation is atomic. All concurrent decrement operations will be
        counted individually.

        Unlike Memcached, negative values are supported. Value may be
        decremented below zero.

        Assumes value may be stored in a SQLite column. Most builds that target
        machines with 64-bit pointer widths will support 64-bit signed
        integers.

        Args:
            key: key for item
            delta: amount to decrement
            default: value if key is missing
            retry: retry if database timeout occurs

        Returns:
            new value for item
        """
        ...

    def evict(
        self,
        tags: str | Iterable[str],
        *,
        method: Literal["and", "or"] | FilterMethod = ...,
        retry: bool = False,
    ) -> int:
        """Remove items with matching `tag` from cache.

        Removing items is an iterative process. In each iteration, a subset of
        items is removed. Concurrent writes may occur between iterations.

        If a :exc:`Timeout` occurs, the first element of the exception's
        `args` attribute will be the number of items removed before the
        exception occurred.

        Args:
            tags: tags identifying items
            method: 'and' or 'or' filter method
            retry: retry if database timeout occurs

        Returns:
            count of rows removed
        """
        ...

    async def aevict(
        self,
        tags: str | Iterable[str],
        *,
        method: Literal["and", "or"] | FilterMethod = ...,
        retry: bool = ...,
    ) -> int:
        """Remove items with matching `tag` from cache.

        Asynchronous version of `evict`.

        Removing items is an iterative process. In each iteration, a subset of
        items is removed. Concurrent writes may occur between iterations.

        If a :exc:`Timeout` occurs, the first element of the exception's
        `args` attribute will be the number of items removed before the
        exception occurred.

        Args:
            tags: tags identifying items
            method: 'and' or 'or' filter method
            retry: retry if database timeout occurs

        Returns:
            count of rows removed
        """
        ...

    def expire(self, now: float | None = ..., *, retry: bool = ...) -> int:
        """Remove expired items from cache.

        Removing items is an iterative process. In each iteration, a subset of
        items is removed. Concurrent writes may occur between iterations.

        If a :exc:`Timeout` occurs, the first element of the exception's
        `args` attribute will be the number of items removed before the
        exception occurred.

        Args:
            now: current time. If None, use `time.time()`.
            retry: retry if database timeout occurs

        Returns:
            count of items removed
        """
        ...

    async def aexpire(self, now: float | None = ..., *, retry: bool = ...) -> int:
        """Remove expired items from cache.

        Asynchronous version of `expire`.

        Removing items is an iterative process. In each iteration, a subset of
        items is removed. Concurrent writes may occur between iterations.

        If a :exc:`Timeout` occurs, the first element of the exception's
        `args` attribute will be the number of items removed before the
        exception occurred.

        Args:
            now: current time. If None, use `time.time()`.
            retry: retry if database timeout occurs

        Returns:
            count of items removed
        """
        ...

    def cull(self, *, retry: bool = ...) -> int:
        """Cull items from cache until volume is less than size limit.

        Removing items is an iterative process. In each iteration, a subset of
        items is removed. Concurrent writes may occur between iterations.

        If a :exc:`Timeout` occurs, the first element of the exception's
        `args` attribute will be the number of items removed before the
        exception occurred.

        Args:
            retry: retry if database timeout occurs

        Returns:
            count of items removed
        """
        ...

    async def acull(self, *, retry: bool = ...) -> int:
        """Cull items from cache until volume is less than size limit.

        Asynchronous version of `cull`.

        Removing items is an iterative process. In each iteration, a subset of
        items is removed. Concurrent writes may occur between iterations.

        If a :exc:`Timeout` occurs, the first element of the exception's
        `args` attribute will be the number of items removed before the
        exception occurred.

        Args:
            retry: retry if database timeout occurs

        Returns:
            count of items removed
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

        When prefix is None, integer keys are used.
        Otherwise, string keys are used.

        Operation is atomic. Concurrent operations will be serialized.

        See also `pull`.

        Args:
            value: value for item
            prefix: key prefix. If None, key is integer
            side: either 'back' or 'front'
            expire: seconds until the key expires. If None, no expiry.
            tags: texts to associate with key
            retry: retry if database timeout occurs

        Returns:
            key for item in cache

        Examples:
            .. code-block:: python

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
        """Push `value` onto `side` of queue identified by `prefix` in cache.

        Asynchronous version of `push`.

        When prefix is None, integer keys are used.
        Otherwise, string keys are used.

        Operation is atomic. Concurrent operations will be serialized.

        See also `pull`.

        Args:
            value: value for item
            prefix: key prefix. If None, key is integer
            side: either 'back' or 'front'
            expire: seconds until the key expires. If None, no expiry.
            tags: texts to associate with key
            retry: retry if database timeout occurs

        Returns:
            key for item in cache

        Examples:
            .. code-block:: python

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

        When prefix is None, integer keys are used.
        Otherwise, string keys are used.

        If queue is empty, return default.

        Operation is atomic. Concurrent operations will be serialized.

        See also `push` and `get`.

        Args:
            prefix: key prefix. If None, key is integer
            default: value to return if key is missing
            side: either 'back' or 'front'
            retry: retry if database timeout occurs

        Returns:
            value for item or default if queue is empty

        Examples:
            .. code-block:: python

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
        """Pull key and value item pair from `side` of queue in cache.

        Asynchronous version of `pull`.

        When prefix is None, integer keys are used.
        Otherwise, string keys are used.

        If queue is empty, return default.

        Operation is atomic. Concurrent operations will be serialized.

        See also `push` and `get`.

        Args:
            prefix: key prefix. If None, key is integer
            default: value to return if key is missing
            side: either 'back' or 'front'
            retry: retry if database timeout occurs

        Returns:
            value for item or default if queue is empty

        Examples:
            .. code-block:: python

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

        When prefix is None, integer keys are used.
        Otherwise, string keys are used.

        If queue is empty, return default.

        Expired items are deleted from cache. Operation is atomic. Concurrent
        operations will be serialized.

        See also `pull` and `push`.

        Args:
            prefix: key prefix. If None, key is integer
            default: value to return if key is missing
            side: either 'back' or 'front'
            retry: retry if database timeout occurs

        Returns:
            value for item or default if queue is empty

        Examples:
            .. code-block:: python

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
        """Peek at key and value item pair from `side` of queue in cache.

        Asynchronous version of `peek`.

        When prefix is None, integer keys are used.
        Otherwise, string keys are used.

        If queue is empty, return default.

        Expired items are deleted from cache. Operation is atomic. Concurrent
        operations will be serialized.

        See also `pull` and `push`.

        Args:
            prefix: key prefix. If None, key is integer
            default: value to return if key is missing
            side: either 'back' or 'front'
            retry: retry if database timeout occurs

        Returns:
            value for item or default if queue is empty

        Examples:
            .. code-block:: python

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
        """
        ...

    def peekitem(self, *, last: bool = ..., retry: bool = ...) -> Container[Any]:
        """Peek at key and value item pair in cache based on iteration order.

        Expired items are deleted from cache. Operation is atomic. Concurrent
        operations will be serialized.

        Args:
            last: last item in iteration order
            retry: retry if database timeout occurs

        Returns:
            value for item

        Examples:
            .. code-block:: python

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
        """
        ...

    async def apeekitem(self, *, last: bool = ..., retry: bool = ...) -> Container[Any]:
        """Peek at key and value item pair in cache based on iteration order.

        Asynchronous version of `peekitem`.

        Expired items are deleted from cache. Operation is atomic. Concurrent
        operations will be serialized.

        Args:
            last: last item in iteration order
            retry: retry if database timeout occurs

        Returns:
            value for item

        Examples:
            .. code-block:: python

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
            fix: correct inconsistencies
            retry: retry if database timeout occurs

        Returns:
            list of warnings
        """
        ...

    async def acheck(
        self, *, fix: bool = ..., retry: bool = ...
    ) -> list[warnings.WarningMessage]:
        """Check database and file system consistency.

        Asynchronous version of `check`.

        Intended for use in testing and post-mortem error analysis.

        While checking the Cache table for consistency, a writer lock is held
        on the database. The lock blocks other cache clients from writing to
        the database. For caches with many file references, the lock may be
        held for a long time. For example, local benchmarking shows that a
        cache with 1,000 file references takes ~60ms to check.

        Args:
            fix: correct inconsistencies
            retry: retry if database timeout occurs

        Returns:
            list of warnings
        """
        ...
        ...

    def iterkeys(self, *, reverse: bool = ...) -> Generator[Any, None, None]:
        """Iterate Cache keys in database sort order.

        Args:
            reverse: reverse sort order

        Yields:
            key of item

        Examples:
            .. code-block:: python

                import typed_diskcache


                def main() -> None:
                    cache = typed_diskcache.Cache()
                    for key in [4, 1, 3, 0, 2]:
                        cache[key] = key
                    print(list(cache.iterkeys()))
                    # [0, 1, 2, 3, 4]
                    print(list(cache.iterkeys(reverse=True)))
                    # [4, 3, 2, 1, 0]
        """
        ...

    async def aiterkeys(self, *, reverse: bool = ...) -> AsyncGenerator[Any, None]:
        """Iterate Cache keys in database sort order.

        Asynchronous version of `iterkeys`.

        Args:
            reverse: reverse sort order

        Yields:
            key of item

        Examples:
            .. code-block:: python

                import typed_diskcache


                async def main() -> None:
                    cache = typed_diskcache.Cache()
                    for key in [4, 1, 3, 0, 2]:
                        cache[key] = key
                    print([x async for x in cache.aiterkeys()])
                    # [0, 1, 2, 3, 4]
                    print([x async for x in cache.aiterkeys(reverse=True)])
                    # [4, 3, 2, 1, 0]
        """
        ...

    def update_settings(self, settings: Settings) -> None:
        """Update cache settings.

        Args:
            settings: new settings
        """
        ...

    async def aupdate_settings(self, settings: Settings) -> None:
        """Update cache settings.

        Asynchronous version of `update_settings`.

        Args:
            settings: new settings
        """
        ...
