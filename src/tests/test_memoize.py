from __future__ import annotations

import time
from typing import Any

import anyio
import anyio.lowlevel
import pytest

from typed_diskcache.utils import memo

pytestmark = pytest.mark.anyio


def test_memoize(cache):
    count = 10

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

    worker.wait()


async def test_async_memoize(cache):
    count = 10

    async def fibiter(num: int) -> int:
        alpha, beta = 0, 1

        for _ in range(num):
            await anyio.lowlevel.checkpoint()
            alpha, beta = beta, alpha + beta

        return alpha

    @memo.memoize(cache)
    async def fibrec(num: int) -> int:
        await anyio.lowlevel.checkpoint()
        if num == 0:
            return 0
        if num == 1:
            return 1

        return await fibrec(num - 1) + await fibrec(num - 2)

    cache.stats(enable=True)

    for value in range(count):
        assert await fibrec(value) == await fibiter(value)

    hits1, misses1 = await cache.astats()

    for value in range(count):
        assert await fibrec(value) == await fibiter(value)

    hits2, misses2 = await cache.astats()

    assert hits2 == (hits1 + count)
    assert misses2 == misses1


async def test_async_memoize_kwargs(cache):
    @memo.memoize(cache, typed=True)
    async def foo(*args: Any, **kwargs: Any) -> Any:
        await anyio.lowlevel.checkpoint()
        return args, kwargs

    assert await foo(1, 2, 3, a=4, b=5) == ((1, 2, 3), {"a": 4, "b": 5})


async def test_async_memoize_ignore(cache):
    @memo.memoize(cache, exclude={1, "arg1"})
    async def test(*args: Any, **kwargs: Any) -> Any:
        await anyio.lowlevel.checkpoint()
        return args, kwargs

    await cache.astats(enable=True)
    assert await test("a", "b", "c", arg0="d", arg1="e", arg2="f")
    assert await test("a", "w", "c", arg0="d", arg1="x", arg2="f")
    assert await test("a", "y", "c", arg0="d", arg1="z", arg2="f")
    assert await cache.astats() == (2, 1)


async def test_async_memoize_iter(cache):
    @memo.memoize(cache)
    async def test(*args: int, **kwargs: int) -> Any:
        await anyio.lowlevel.checkpoint()
        return sum(args) + sum(kwargs.values())

    await cache.aclear()
    assert await test(1, 2, 3)
    assert await test(a=1, b=2, c=3)
    assert await test(-1, 0, 1, a=1, b=2, c=3)
    assert len(cache) == 3
    async for key in cache:
        assert cache[key].value == 6


async def test_async_memoize_stampede(cache):
    state = {"num": 0}

    @memo.memoize_stampede(cache, beta=0.1)
    async def worker(num: int) -> int:
        await anyio.sleep(0.01)
        state["num"] += 1
        return num

    start = time.time()
    while (time.time() - start) < 1:
        await worker(100)
    assert state["num"] > 0

    worker.wait()
