from __future__ import annotations

import pytest

from typed_diskcache import exception as te
from typed_diskcache.core.types import EvictionPolicy
from typed_diskcache.utils.deque import Deque

pytestmark = pytest.mark.anyio


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


def test_set_maxlen(deque):
    assert deque.maxlen == float("inf")
    deque.extendleft("abcde")
    deque.maxlen = 3
    assert deque.maxlen == 3
    assert list(deque) == ["c", "b", "a"]


def test_append(deque):
    deque.append("a")
    deque.append("b")
    deque.append("c")
    assert list(deque) == ["a", "b", "c"]
