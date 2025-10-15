from __future__ import annotations

import threading
import time

import anyio
import pytest

import typed_diskcache
from typed_diskcache.core.const import IS_FREE_THREAD

pytestmark = pytest.mark.anyio


def test_lock(cache):
    state = {"num": 0}
    lock = typed_diskcache.SyncLock(cache, "demo")

    def worker() -> None:
        state["num"] += 1
        with lock:
            assert lock.locked
            state["num"] += 1
            time.sleep(0.1)

    with lock:
        thread = threading.Thread(target=worker)
        thread.start()
        time.sleep(0.1)
        assert state["num"] == 1
    thread.join()
    assert state["num"] == 2


def test_rlock(cache):
    state = {"num": 0}
    rlock = typed_diskcache.SyncRLock(cache, "demo")

    def worker() -> None:
        state["num"] += 1
        with rlock:
            with rlock:
                state["num"] += 1
                time.sleep(0.1)

    with rlock:
        thread = threading.Thread(target=worker)
        thread.start()
        time.sleep(0.1)
        assert state["num"] == 1
    thread.join()
    assert state["num"] == 2


def test_semaphore(cache):
    state = {"num": 0}
    semaphore = typed_diskcache.SyncSemaphore(cache, "demo", value=3)

    def worker() -> None:
        state["num"] += 1
        with semaphore:
            state["num"] += 1
            time.sleep(0.1)

    semaphore.acquire()
    semaphore.acquire()
    with semaphore:
        thread = threading.Thread(target=worker)
        thread.start()
        time.sleep(0.1)
        assert state["num"] == 1
    thread.join()
    assert state["num"] == 2
    semaphore.release()
    semaphore.release()


@pytest.mark.skipif(
    IS_FREE_THREAD, reason="AsyncLock does not support free-threading mode."
)
async def test_async_lock(cache):
    state = {"num": 0}
    lock = typed_diskcache.AsyncLock(cache, "demo")

    async def worker() -> None:
        state["num"] += 1
        async with lock:
            assert lock.locked
            state["num"] += 1
            await anyio.sleep(0.1)

    async with lock:
        thread = threading.Thread(target=anyio.run, args=(worker,))
        thread.start()
        await anyio.sleep(0.1)
        assert state["num"] == 1
    thread.join()
    assert state["num"] == 2


@pytest.mark.skipif(
    IS_FREE_THREAD, reason="AsyncRLock does not support free-threading mode."
)
async def test_async_rlock(cache):
    state = {"num": 0}
    rlock = typed_diskcache.AsyncRLock(cache, "demo")

    async def worker() -> None:
        state["num"] += 1
        async with rlock:
            async with rlock:
                state["num"] += 1
                await anyio.sleep(0.1)

    async with rlock:
        thread = threading.Thread(target=anyio.run, args=(worker,))
        thread.start()
        await anyio.sleep(0.1)
        assert state["num"] == 1
    thread.join()
    assert state["num"] == 2


@pytest.mark.skipif(
    IS_FREE_THREAD, reason="AsyncSemaphore does not support free-threading mode."
)
async def test_async_semaphore(cache):
    state = {"num": 0}
    semaphore = typed_diskcache.AsyncSemaphore(cache, "demo", value=3)

    async def worker() -> None:
        state["num"] += 1
        async with semaphore:
            state["num"] += 1
            await anyio.sleep(0.1)

    await semaphore.acquire()
    await semaphore.acquire()
    async with semaphore:
        thread = threading.Thread(target=anyio.run, args=(worker,))
        thread.start()
        await anyio.sleep(0.1)
        assert state["num"] == 1
    thread.join()
    assert state["num"] == 2
    await semaphore.release()
    await semaphore.release()


@pytest.mark.skipif(not IS_FREE_THREAD, reason="Only test in free-threading mode.")
@pytest.mark.parametrize(
    "lock_cls",
    [
        typed_diskcache.AsyncLock,
        typed_diskcache.AsyncRLock,
        typed_diskcache.AsyncSemaphore,
    ],
)
def test_async_lock_warning(cache, lock_cls):
    with pytest.warns(RuntimeWarning):
        lock_cls(cache, "demo")
