from __future__ import annotations

import operator as op
import shutil
from collections.abc import Callable, Iterable, Iterator, MutableSequence, Sequence
from contextlib import suppress
from functools import partial
from typing import TYPE_CHECKING, Any, Generic, SupportsIndex

from typing_extensions import Self, TypeVar, override

from typed_diskcache import Cache
from typed_diskcache.core.context import context
from typed_diskcache.core.types import EvictionPolicy
from typed_diskcache.database.connect import transact
from typed_diskcache.log import get_logger

if TYPE_CHECKING:
    from os import PathLike
    from pathlib import Path


_T = TypeVar("_T", infer_variance=True)
logger = get_logger()


class Deque(MutableSequence[_T], Generic[_T]):
    """Persistent sequence with double-ended queue semantics.

    Double-ended queue is an ordered collection with optimized access at its
    endpoints.

    Items are serialized to disk. Deque may be initialized from directory path
    where items are stored.

    Args:
        values: values to initialize deque.
            Defaults to None.
        maxlen: maximum length of deque.
            Defaults to None(infinite).
        directory: directory path to store items.
            Defaults to None.
        **kwargs: additional cache options.

    Examples:
        ```python
        from typed_diskcache.utils.deque import Deque


        def main() -> None:
            deque = Deque()
            deque += range(5)
            print(list(deque))
            # [0, 1, 2, 3, 4]
            for value in range(5):
                deque.appendleft(-value)
            print(len(deque))
            # 10
            print(list(deque))
            # [-4, -3, -2, -1, 0, 0, 1, 2, 3, 4]
            print(deque.pop())
            # 4
            print(deque.popleft())
            # -4
            deque.reverse()
            print(list(deque))
            # [3, 2, 1, 0, 0, -1, -2, -3]
        ```
    """

    __slots__ = ("_cache", "_maxlen")

    def __init__(
        self,
        values: Iterable[_T] | None = None,
        maxlen: float | None = None,
        *,
        directory: str | PathLike[str] | None = None,
        **kwargs: Any,
    ) -> None:
        eviction_policy = kwargs.pop("eviction_policy", EvictionPolicy.NONE)
        if eviction_policy != EvictionPolicy.NONE:
            logger.warning("Deque eviction policy must be none")

        kwargs["eviction_policy"] = EvictionPolicy.NONE
        self._cache = Cache(directory=directory, **kwargs)
        self._maxlen = float("inf") if maxlen is None else maxlen
        super().extend(values or [])

    @property
    def cache(self) -> Cache:
        """Cache object for deque."""
        return self._cache

    @property
    def maxlen(self) -> float:
        """Maximum length of deque."""
        return self._maxlen

    @maxlen.setter
    @context("Deque.maxlen", override=True)
    def maxlen(self, value: float) -> None:
        """Set max length of the deque.

        Pops items from left while length greater than max.

        Args:
            value: max length

        Examples:
            ```python
            from typed_diskcache.utils.deque import Deque


            def main() -> None:
                deque = Deque()
                deque.extendleft("abcde")
                deque.maxlen = 3
                print(list(deque))
                # ['c', 'd', 'e']
            ```
        """
        self._maxlen = value
        with self.cache.conn.sync_session as session:
            with transact(session):
                while len(self.cache) > self._maxlen:
                    self.popleft()

    @context("Deque.append", override=True)
    @override
    def append(self, value: _T) -> None:
        """Add `value` to back of deque.

        Args:
            value: value to add to back of deque

        Examples:
            ```python
            from typed_diskcache.utils.deque import Deque


            def main() -> None:
                deque = Deque()
                deque.append("a")
                deque.append("b")
                deque.append("c")
                print(list(deque))
                # ['a', 'b', 'c']
            ```
        """
        with self.cache.conn.sync_session as session:
            with transact(session):
                self.cache.push(value, side="back", retry=True)
                if len(self.cache) > self._maxlen:
                    self.popleft()

    @context("Deque.appendleft", override=True)
    def appendleft(self, value: _T) -> None:
        """Add `value` to front of deque.

        Args:
            value: value to add to front of deque

        Examples:
            ```python
            from typed_diskcache.utils.deque import Deque


            def main() -> None:
                deque = Deque()
                deque.appendleft("a")
                deque.appendleft("b")
                deque.appendleft("c")
                list(deque)
                # ['c', 'b', 'a']
            ```
        """
        with self.cache.conn.sync_session as session:
            with transact(session):
                self.cache.push(value, side="front", retry=True)
                if len(self.cache) > self._maxlen:
                    self.pop()

    def copy(self) -> Self:
        """Copy deque with same directory and max length."""
        new = object.__new__(type(self))
        new._cache = self.cache  # noqa: SLF001
        new._maxlen = self.maxlen  # noqa: SLF001
        return new

    @override
    def count(self, value: _T) -> int:
        """Return number of occurrences of `value` in deque.

        Args:
            value: value to count in deque

        Returns:
            count of items equal to value in deque

        Examples:
            ```python
            from typed_diskcache.utils.deque import Deque


            def main() -> None:
                deque = Deque()
                deque += [num for num in range(1, 5) for _ in range(num)]
                print(deque.count(0))
                # 0
                print(deque.count(1))
                # 1
                print(deque.count(4))
                # 4
            ```
        """
        return sum(1 for item in self if item == value)

    @context("Deque.extend", override=True)
    @override
    def extend(self, values: Iterable[_T]) -> None:
        """Extend back side of deque with values from `iterable`.

        Args:
            values: iterable of values to append to deque
        """
        for value in values:
            self.append(value)

    @context("Deque.extendleft", override=True)
    def extendleft(self, values: Iterable[_T]) -> None:
        """Extend front side of deque with value from `iterable`.

        Args:
            values: iterable of values to append to deque

        Examples:
            ```python
            from typed_diskcache.utils.deque import Deque


            def main() -> None:
                deque = Deque()
                deque.extendleft("abc")
                print(list(deque))
                # ['c', 'b', 'a']
            ```
        """
        for value in values:
            self.appendleft(value)

    @override
    def insert(self, index: int, value: _T) -> None:
        if index >= 0:
            self.rotate(-index)
            self.appendleft(value)
            self.rotate(index)
            return
        self.rotate(-index - 1)
        self.append(value)
        self.rotate(index + 1)

    @override
    def index(self, value: _T, start: int = 0, stop: int = 0) -> int:
        size = len(self)
        if stop <= 0:
            stop = size - 1
        stop = min(stop, size - 1)
        for index, key in enumerate(self.cache.iterkeys()):
            if index < start:
                continue
            if index > stop:
                error_msg = f"{value!r} is not in deque"
                raise ValueError(error_msg)
            with suppress(KeyError):
                container = self.cache[key]
                if value == container.value:
                    return index

        error_msg = f"{value!r} is not in deque"
        raise ValueError(error_msg)

    @override
    def pop(self) -> _T:  # pyright: ignore[reportIncompatibleMethodOverride]
        """Remove and return value at back of deque.

        If deque is empty then raise IndexError.

        Returns:
            value at back of deque

        Examples:
            ```python
            from typed_diskcache.utils.deque import Deque


            def main() -> None:
                deque = Deque()
                deque += "ab"
                print(deque.pop())
                # 'b'
                print(deque.pop())
                # 'a'
                deque.pop()
                # Traceback (most recent call last):
                #     ...
                # IndexError: pop from an empty deque
            ```
        """
        container = self.cache.pull(side="back", retry=True)
        if container.default:
            raise IndexError("pop from an empty deque")
        return container.value

    def popleft(self) -> _T:
        """Remove and return value at front of deque.

        Returns:
            value at front of deque

        Examples:
            ```python
            from typed_diskcache.utils.deque import Deque


            def main() -> None:
                deque = Deque()
                deque += "ab"
                print(deque.popleft())
                # 'a'
                print(deque.popleft())
                # 'b'
                deque.popleft()
                # Traceback (most recent call last):
                #     ...
                # IndexError: pop from an empty deque
            ```
        """
        container = self.cache.pull(side="front", retry=True)
        if container.default:
            raise IndexError("pop from an empty deque")
        return container.value

    @override
    def remove(self, value: _T) -> None:
        """Remove first occurrence of `value` in deque.

        Args:
            value: value to remove

        Examples:
            ```python
            from typed_diskcache.utils.deque import Deque


            def main() -> None:
                deque = Deque()
                deque += "aab"
                deque.remove("a")
                print(list(deque))
                # ['a', 'b']
                deque.remove("b")
                print(list(deque))
                # ['a']
                deque.remove("c")
                # Traceback (most recent call last):
                #     ...
                # ValueError: deque.remove(value): value not in deque
            ```
        """
        for key in self.cache.iterkeys():
            with suppress(KeyError):
                item = self.cache[key]
                if value == item:
                    del self.cache[key]
                    return

    def rotate(self, steps: int = 1) -> None:
        """Rotate deque right by `steps`.

        If steps is negative then rotate left.

        Args:
            steps: number of steps to rotate.
                Defaults to 1.

        Examples:
            ```python
            from typed_diskcache.utils.deque import Deque


            def main() -> None:
                deque = Deque()
                deque += range(5)
                deque.rotate(2)
                print(list(deque))
                # [3, 4, 0, 1, 2]
                deque.rotate(-1)
                print(list(deque))
                # [4, 0, 1, 2, 3]
            ```
        """
        size = len(self)
        if not size:
            return

        if steps >= 0:
            steps %= size
            for _ in range(steps):
                try:
                    value = self.pop()
                except IndexError:
                    return
                self.appendleft(value)

            return

        steps *= -1
        steps %= size
        for _ in range(steps):
            try:
                value = self.popleft()
            except IndexError:
                return
            self.append(value)

    @override
    def reverse(self) -> None:
        """Reverse deque in place.

        Examples:
            ```python
            from typed_diskcache.utils.deque import Deque


            def main() -> None:
                deque = Deque()
                deque += "abc"
                deque.reverse()
                list(deque)
                # ['c', 'b', 'a']
            ```
        """
        temp = Deque(reversed(self), maxlen=self.maxlen)
        self.clear()
        self.extend(temp)
        temp._cache.close()  # noqa: SLF001
        temp_directory = temp._cache.directory  # noqa: SLF001
        del temp
        shutil.rmtree(temp_directory)

    @override
    def clear(self) -> None:
        """Remove all elements from deque.

        Examples:
            ```python
            from typed_diskcache.utils.deque import Deque


            def main() -> None:
                deque = Deque("abc")
                print(len(deque))
                # 3
                deque.clear()
                print(list(deque))
                # []
            ```
        """
        self.cache.clear(retry=True)

    def __copy__(self) -> Self:
        return self.copy()

    def __deepcopy__(self, memo: dict[int, Any]) -> Self:
        new = type(self)(maxlen=self.maxlen)
        new.extend(self)
        memo[id(self)] = new
        return new

    @override
    def __len__(self) -> int:
        """deque.__len__() <==> len(deque)

        Returns:
            length of deque
        """
        return len(self.cache)

    @override
    def __getitem__(self, key: SupportsIndex) -> _T:  # pyright: ignore[reportIncompatibleMethodOverride]
        """deque.__getitem__(index) <==> deque[index]

        Return corresponding item for `index` in deque.

        Args:
            key: index of item

        Returns:
            corresponding item

        Examples:
            ```python
            from typed_diskcache.utils.deque import Deque


            def main() -> None:
                deque = Deque()
                deque.extend("abcde")
                deque[1]
                # 'b'
                deque[-2]
                # 'd'
            ```
        """
        return _index_deque(self, self.cache, key, partial(_get_item, self.cache))

    @override
    def __setitem__(self, key: SupportsIndex, value: _T) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        """deque.__setitem__(index, value) <==> deque[index] = value

        Store `value` in deque at `index`.

        Args:
            key: index of item
            value: value to store

        Examples:
            ```python
            from typed_diskcache.utils.deque import Deque


            def main() -> None:
                deque = Deque()
                deque.extend([None] * 3)
                deque[0] = "a"
                deque[1] = "b"
                deque[-1] = "c"
                print("".join(deque))
                # 'abc'
            ```
        """
        set_value = partial(self.cache.__setitem__, value=value)
        _index_deque(self, self.cache, key, set_value)

    @override
    def __delitem__(self, key: SupportsIndex) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        """deque.__delitem__(index) <==> del deque[index]

        Delete item in deque at `index`.

        Args:
            key: index of item

        Examples:
            ```python
            from typed_diskcache.utils.deque import Deque


            def main() -> None:
                deque = Deque()
                deque.extend([None] * 3)
                del deque[0]
                del deque[1]
                del deque[-1]
                print(len(deque))
                # 0
            ```
        """
        _index_deque(self, self.cache, key, self.cache.__delitem__)

    @override
    def __contains__(self, value: object) -> bool:
        for key in self.cache.iterkeys():
            with suppress(KeyError):
                item = self.cache[key]
                if value == item:
                    return True

        return False

    @override
    def __iadd__(self, values: Iterable[_T]) -> Self:
        """deque.__iadd__(iterable) <==> deque += iterable

        Extend back side of deque with items from iterable.

        Args:
            values: iterable of items to append to deque

        Returns:
            deque with added items
        """
        self.extend(values)
        return self

    @override
    def __iter__(self) -> Iterator[_T]:
        """deque.__iter__() <==> iter(deque)

        Yields:
            item in deque from front to back
        """
        for key in self.cache.iterkeys():
            with suppress(KeyError):
                container = self.cache[key]
                yield container.value

    @override
    def __reversed__(self) -> Iterator[_T]:
        """deque.__reversed__() <==> reversed(deque)

        Yields:
            item in deque from back to front

        Examples:
            ```python
            from typed_diskcache.utils.deque import Deque


            def main() -> None:
                deque = Deque()
                deque.extend("abcd")
                iterator = reversed(deque)
                print(next(iterator))
                # 'd'
                print(list(iterator))
                # ['c', 'b', 'a']
            ```
        """
        for key in self.cache.iterkeys(reverse=True):
            with suppress(KeyError):
                container = self.cache[key]
                yield container.value

    def __add__(self, value: Self) -> Self:
        new = self.copy()
        new.extend(value)
        return new

    def __mul__(self, value: int) -> Self:
        new = self.copy()
        new *= value
        return new

    def __imul__(self, value: int) -> Self:
        for _ in range(len(self)):
            left = self.popleft()
            self.append(left * value)  # pyright: ignore[reportOperatorIssue]
        return self

    def __lt__(self, value: Sequence[_T]) -> bool:
        for left, right in zip(self, value):
            if left == right:
                continue
            return op.lt(left, right)  # pyright: ignore[reportArgumentType]
        return len(self) < len(value)

    def __le__(self, value: Sequence[_T]) -> bool:
        for left, right in zip(self, value):
            return op.le(left, right)  # pyright: ignore[reportArgumentType]
        return len(self) <= len(value)

    def __gt__(self, value: Sequence[_T]) -> bool:
        for left, right in zip(self, value):
            if left == right:
                continue
            return op.gt(left, right)  # pyright: ignore[reportArgumentType]
        return len(self) > len(value)

    def __ge__(self, value: Sequence[_T]) -> bool:
        for left, right in zip(self, value):
            return op.ge(left, right)  # pyright: ignore[reportArgumentType]
        return len(self) >= len(value)

    @override
    def __eq__(self, value: object) -> bool:
        if not isinstance(value, Deque):
            return False

        if not len(self) == len(value):
            return False

        return all(left == right for left, right in zip(self, value))

    @override
    def __repr__(self) -> str:
        """deque.__repr__() <==> repr(deque)

        Returns:
            string representation of deque
        """
        return f"{type(self).__name__}(maxlen={self.maxlen})"

    def __getstate__(self) -> tuple[Path, float]:
        return self.cache.directory, self.maxlen

    def __setstate__(self, state: tuple[Path, float]) -> None:
        self._cache = Cache(directory=state[0], eviction_policy=EvictionPolicy.NONE)
        self._maxlen = state[1]

    def __del__(self) -> None:
        with suppress(BaseException):
            self.clear()
            self.cache.close()


def _index_deque(
    deque: Deque[Any], cache: Cache, index: SupportsIndex, func: Callable[[Any], _T]
) -> _T:
    size = len(deque)
    index = index.__index__()

    if index >= 0:
        if index > size:
            raise IndexError("index out of range")

        for key in cache.iterkeys():
            if index == 0:
                with suppress(KeyError):
                    return func(key)
            index -= 1
        raise IndexError("index out of range")

    if index < -size:
        raise IndexError("index out of range")

    index += 1
    for key in cache.iterkeys(reverse=True):
        if index == 0:
            with suppress(KeyError):
                return func(key)
        index += 1

    raise IndexError("index out of range")


def _get_item(cache: Cache, key: Any) -> Any:
    return cache[key].value
