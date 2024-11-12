from __future__ import annotations

import pickle
import re
from copy import copy, deepcopy

import pytest

from typed_diskcache import exception as te
from typed_diskcache.core.types import EvictionPolicy
from typed_diskcache.utils.deque import Deque


@pytest.fixture
def deque(cache_directory):
    deque = Deque(directory=cache_directory)
    try:
        yield deque
    finally:
        deque.cache.close()


@pytest.mark.parametrize(
    ("maxlen", "expected"), [(None, float("inf")), (1, 1), (10, 10)]
)
def test_attributes(cache_directory, maxlen, expected):
    deque = Deque(directory=cache_directory, maxlen=maxlen)
    assert deque.cache.directory == cache_directory
    assert deque.maxlen == expected


@pytest.mark.parametrize("eviction_policy", [x for x in EvictionPolicy if x != "none"])
def test_eviction_warning(cache_directory, eviction_policy):
    with pytest.warns(te.TypedDiskcacheWarning):
        Deque(directory=cache_directory, eviction_policy=eviction_policy)


def test_append(deque):
    deque.append("a")
    deque.append("b")
    deque.append("c")
    assert list(deque) == ["a", "b", "c"]


def test_appendleft(deque):
    deque.appendleft("a")
    deque.appendleft("b")
    deque.appendleft("c")
    assert list(deque) == ["c", "b", "a"]


def test_copy(deque):
    deque.extendleft("abcde")
    new = copy(deque)
    assert new == deque
    assert new is not deque
    assert new.cache is deque.cache
    assert new.maxlen == deque.maxlen


def test_copy_method(deque):
    deque.extendleft("abcde")
    new = deque.copy()
    assert new == deque
    assert new is not deque
    assert new.cache is deque.cache
    assert new.maxlen == deque.maxlen


def test_deepcopy(deque):
    deque.extendleft("abcde")
    new = deepcopy(deque)
    assert new == deque
    assert new is not deque
    assert new.cache is not deque.cache
    assert new.cache.directory != deque.cache.directory
    assert new.maxlen == deque.maxlen


def test_count(deque):
    deque.extendleft("abcde")
    deque += [num for num in range(1, 5) for _ in range(num)]
    assert deque.count(0) == 0
    assert deque.count(1) == 1
    assert deque.count(4) == 4


def test_extend(deque):
    deque.extend("abc")
    assert list(deque) == ["a", "b", "c"]


def test_extendleft(deque):
    deque.extendleft("abc")
    assert list(deque) == ["c", "b", "a"]


def test_insert(deque):
    deque.extend("abc")
    deque.insert(1, "d")
    assert list(deque) == ["a", "d", "b", "c"]


def test_index(deque):
    deque.extend("abcde")
    assert deque.index("a") == 0
    assert deque.index("c") == 2
    assert deque.index("e") == 4


def test_pop(deque):
    deque += "ab"
    assert deque.pop() == "b"
    assert deque.pop() == "a"
    with pytest.raises(te.TypedDiskcacheIndexError, match="pop from an empty deque"):
        deque.pop()


def test_popleft(deque):
    deque += "ab"
    assert deque.popleft() == "a"
    assert deque.popleft() == "b"
    with pytest.raises(te.TypedDiskcacheIndexError, match="pop from an empty deque"):
        deque.popleft()


def test_remove(deque):
    deque += "aab"
    deque.remove("a")
    assert list(deque) == ["a", "b"]
    deque.remove("b")
    assert list(deque) == ["a"]
    with pytest.raises(
        te.TypedDiskcacheValueError,
        match=re.escape("deque.remove(value): value not in deque"),
    ):
        deque.remove("c")


def test_rotate(deque):
    deque += range(5)
    deque.rotate(2)
    assert list(deque) == [3, 4, 0, 1, 2]
    deque.rotate(-1)
    assert list(deque) == [4, 0, 1, 2, 3]


def test_reverse(deque):
    deque += "abc"
    deque.reverse()
    assert list(deque) == ["c", "b", "a"]


def test_clear(deque):
    deque += "abc"
    assert list(deque) == ["a", "b", "c"]
    deque.clear()
    assert list(deque) == []


def test_length(deque):
    assert len(deque) == 0
    deque += "abc"
    assert len(deque) == 3


def test_getitem(deque):
    deque.extend("abcde")
    assert deque[1] == "b"
    assert deque[-2] == "d"


def test_seitem(deque):
    deque.extend([None] * 3)
    deque[0] = "a"
    deque[1] = "b"
    deque[-1] = "c"
    assert "".join(deque) == "abc"


def test_delitem(deque):
    deque.extend([None] * 3)
    del deque[0]
    del deque[1]
    del deque[-1]
    assert len(deque) == 0


def test_contains(deque):
    deque.extend("abc")
    assert "a" in deque
    assert "d" not in deque


def test_iadd(deque):
    deque += "abc"
    assert list(deque) == ["a", "b", "c"]
    deque += "def"
    assert list(deque) == ["a", "b", "c", "d", "e", "f"]


# TODO: test_iter


def test_reversed(deque):
    deque.extend("abcd")
    iterator = reversed(deque)
    assert next(iterator) == "d"
    assert list(iterator) == ["c", "b", "a"]


def test_add(deque):
    deque += "abc"
    assert list(deque) == ["a", "b", "c"]
    new = deque + "def"
    assert new is not deque
    assert new.cache is deque.cache
    assert list(new) == ["a", "b", "c", "d", "e", "f"]
    assert list(deque) == ["a", "b", "c", "d", "e", "f"]


def test_mul(deque):
    deque += "abc"
    assert list(deque) == ["a", "b", "c"]
    new = deque * 2
    assert new is not deque
    assert new.cache is deque.cache
    assert list(new) == ["aa", "bb", "cc"]
    assert list(deque) == ["aa", "bb", "cc"]


def test_imul(deque):
    deque += "abc"
    assert list(deque) == ["a", "b", "c"]
    deque *= 2
    assert list(deque) == ["aa", "bb", "cc"]


# TODO: test_lt
# TODO: test_le
# TODO: test_gt
# TODO: test_ge
# TODO: test_ge
# TODO: test_eq


def test_repr():
    deque = Deque()
    assert repr(deque) == "Deque(maxlen=inf)"
    deque = Deque(maxlen=3)
    assert repr(deque) == "Deque(maxlen=3)"


def test_pickle(cache_directory):
    deque = Deque(directory=cache_directory, maxlen=3)
    deque += "abc"
    dump = pickle.dumps(deque)
    new = pickle.loads(dump)  # noqa: S301
    assert new.cache is not deque.cache
    assert new.cache.directory == deque.cache.directory
    assert new.maxlen == deque.maxlen
    assert list(new) == list(deque)


# TODO: test_del
