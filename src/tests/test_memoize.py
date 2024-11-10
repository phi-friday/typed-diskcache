from __future__ import annotations

import time
from typing import Any

import pytest

from typed_diskcache.utils import memo

pytestmark = pytest.mark.anyio


@pytest.mark.timeout(60)
def test_memoize(cache):
    count = 1000

    def fibiter(num: int) -> int:
        alpha, beta = 0, 1

        for _ in range(num):
            alpha, beta = beta, alpha + beta

        return alpha

    @memo.memoize(cache)
    def fibrec(num: int) -> int:
        if num == 0:
            return 0
        if num == 1:
            return 1

        return fibrec(num - 1) + fibrec(num - 2)

    cache.stats(enable=True)

    for value in range(count):
        assert fibrec(value) == fibiter(value)

    hits1, misses1 = cache.stats()

    for value in range(count):
        assert fibrec(value) == fibiter(value)

    hits2, misses2 = cache.stats()

    assert hits2 == (hits1 + count)
    assert misses2 == misses1


def test_memoize_kwargs(cache):
    @memo.memoize(cache, typed=True)
    def foo(*args: Any, **kwargs: Any) -> Any:
        return args, kwargs

    assert foo(1, 2, 3, a=4, b=5) == ((1, 2, 3), {"a": 4, "b": 5})


def test_memoize_ignore(cache):
    @memo.memoize(cache, exclude={1, "arg1"})
    def test(*args: Any, **kwargs: Any) -> Any:
        return args, kwargs

    cache.stats(enable=True)
    assert test("a", "b", "c", arg0="d", arg1="e", arg2="f")
    assert test("a", "w", "c", arg0="d", arg1="x", arg2="f")
    assert test("a", "y", "c", arg0="d", arg1="z", arg2="f")
    assert cache.stats() == (2, 1)


def test_memoize_iter(cache):
    @memo.memoize(cache)
    def test(*args: int, **kwargs: int) -> Any:
        return sum(args) + sum(kwargs.values())

    cache.clear()
    assert test(1, 2, 3)
    assert test(a=1, b=2, c=3)
    assert test(-1, 0, 1, a=1, b=2, c=3)
    assert len(cache) == 3
    for key in cache:
        assert cache[key].value == 6


def test_memoize_stampede(cache):
    state = {"num": 0}

    @memo.memoize_stampede(cache, beta=0.1)
    def worker(num: int) -> int:
        time.sleep(0.01)
        state["num"] += 1
        return num

    start = time.time()
    while (time.time() - start) < 1:
        worker(100)
    assert state["num"] > 0
