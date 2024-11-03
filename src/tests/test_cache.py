from __future__ import annotations

import inspect
import pickle
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, wait
from contextlib import suppress
from functools import partial
from itertools import product
from pathlib import Path
from typing import Any, Literal

import anyio
import anyio.lowlevel
import pytest

import typed_diskcache
from typed_diskcache import exception as te
from typed_diskcache import interface
from typed_diskcache.database import Connection
from typed_diskcache.model import Settings

pytestmark = pytest.mark.anyio


class CacheWrapper:
    def __init__(self, cache: interface.CacheProtocol, *, is_async: bool) -> None:
        self.__cache = cache
        self.__is_async = is_async

    def __getattr__(self, name: str) -> Any:
        value = getattr(self.__cache, name)
        if callable(value) and name.startswith("a") and not self.__is_async:
            with suppress(AttributeError):
                value = getattr(self.__cache, name[1:])
        if not callable(value):
            return value

        return unwrap(value)


def unwrap(func: Callable[..., Any]) -> Any:
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        value = func(*args, **kwargs)
        if inspect.isawaitable(value):
            return await value
        await anyio.lowlevel.checkpoint()
        return value

    return wrapper


@pytest.mark.parametrize(
    ("cache_type", "is_async"),
    [
        pytest.param("cache", True, id="cache-async"),
        pytest.param("cache", False, id="cache-sync"),
        pytest.param("fanoutcache", True, id="fanoutcache-async"),
        pytest.param("fanoutcache", False, id="fanoutcache-sync"),
    ],
)
class TestCache:
    cache_type: Literal["cache", "fanoutcache"]
    origin_cache: interface.CacheProtocol
    cache: interface.CacheProtocol

    @pytest.fixture(autouse=True)
    def _init(self, cache_directory, cache_type, is_async):  # noqa: ANN202
        if cache_type == "cache":
            self.cache_type = "cache"
            self.origin_cache = typed_diskcache.Cache(cache_directory, timeout=5)
        elif cache_type == "fanoutcache":
            self.cache_type = "fanoutcache"
            self.origin_cache = typed_diskcache.FanoutCache(cache_directory, timeout=5)
        else:
            error_msg = f"Unknown cache type: {cache_type}"
            raise RuntimeError(error_msg)
        self.cache = CacheWrapper(self.origin_cache, is_async=is_async)  # pyright: ignore[reportAttributeAccessIssue]
        try:
            yield None
        finally:
            self.origin_cache.close()

    def test_is_cache(self):
        assert isinstance(self.origin_cache, interface.CacheProtocol)

    def test_cache_attributes(self):
        assert isinstance(self.origin_cache.directory, Path)
        assert isinstance(self.origin_cache.timeout, float)
        assert isinstance(self.origin_cache.disk, interface.DiskProtocol)
        assert isinstance(self.origin_cache.conn, Connection)
        assert isinstance(self.origin_cache.settings, Settings)
        assert self.origin_cache.settings is self.origin_cache.conn._settings  # noqa: SLF001

    def test_cache_settings(self):
        settings = self.cache.settings
        default_settings = Settings()
        exclude = {"serialized_disk", "size_limit"}
        assert settings.model_dump(exclude=exclude) == default_settings.model_dump(
            exclude=exclude
        )

    async def test_length(self):
        assert len(self.origin_cache) == 0
        assert await self.cache.aset(0, 0)
        assert len(self.origin_cache) == 1
        assert await self.cache.aset(0, 1)
        assert len(self.origin_cache) == 1
        assert await self.cache.aset(1, 2)
        assert len(self.origin_cache) == 2
        assert await self.cache.adelete(0)
        assert len(self.origin_cache) == 1
        assert not await self.cache.adelete(0)
        assert len(self.origin_cache) == 1
        assert await self.cache.adelete(1)
        assert len(self.origin_cache) == 0

    def test_get_item_error(self, uid):
        with pytest.raises(te.TypedDiskcacheKeyError):
            self.origin_cache[uid]

    def test_getset_item(self, uid):
        key = 0
        assert len(self.origin_cache) == 0
        self.origin_cache[key] = uid
        assert len(self.origin_cache) == 1
        container = self.origin_cache[key]
        assert isinstance(container, typed_diskcache.Container)
        assert not container.default
        assert container.value == uid
        assert container.key == key

    def test_contains(self, uid):
        key = 0
        assert key not in self.origin_cache
        self.origin_cache[key] = uid
        assert key in self.origin_cache
        del self.origin_cache[key]
        assert key not in self.origin_cache

    @pytest.mark.parametrize(
        "value",
        [
            None,
            pytest.param((None,) * 2**20, id="tuple"),
            1234,
            pytest.param(2**512, id="big_int"),
            56.78,
            "hello",
            pytest.param("hello" * 2**20, id="big_str"),
            b"world",
            pytest.param(b"world" * 2**20, id="big_bytes"),
        ],
    )
    def test_getsetdel_item(self, value):
        key = 0
        assert len(self.origin_cache) == 0
        self.origin_cache[key] = value
        assert len(self.origin_cache) == 1
        assert key in self.origin_cache
        container = self.origin_cache[key]
        assert isinstance(container, typed_diskcache.Container)
        assert not container.default
        assert container.value == value
        assert container.key == key
        del self.origin_cache[key]
        assert len(self.origin_cache) == 0
        assert key not in self.origin_cache

    def test_iter_cache(self):
        iter_type = set if self.cache_type == "fanoutcache" else list
        keys = iter_type(range(10))
        for key in keys:
            self.origin_cache[key] = key
        assert iter_type(self.origin_cache) == keys

    def test_reversed_iter_cache(self):
        iter_type = set if self.cache_type == "fanoutcache" else list
        keys = iter_type(range(10))
        for key in keys:
            self.origin_cache[key] = key
        if self.cache_type == "cache":
            keys = list(keys)[::-1]
        assert iter_type(reversed(self.origin_cache)) == keys

    async def test_aiter_cache(self):
        iter_type = set if self.cache_type == "fanoutcache" else list
        keys = list(range(10))
        for key in keys:
            self.origin_cache[key] = key
        result = [key async for key in self.origin_cache]
        assert iter_type(result) == iter_type(keys)

    def test_pickle(self, uid):
        as_bytes = pickle.dumps(self.origin_cache)
        cache = pickle.loads(as_bytes)  # noqa: S301

        assert isinstance(cache, type(self.origin_cache))
        assert cache.directory == self.origin_cache.directory
        assert cache.timeout == self.origin_cache.timeout
        assert cache.settings == self.origin_cache.settings

        key = 0
        self.origin_cache[key] = uid
        assert key in cache

    async def test_getset(self):
        key = 0
        value = await self.cache.aget(key)
        assert isinstance(value, typed_diskcache.Container)
        assert value.default
        assert value.value is None
        assert not value.expire_time
        assert not value.tags
        assert not value.key

        assert (await self.cache.aget(key, "dne")).value == "dne"
        assert (await self.cache.aget(key, {})).value == {}

        assert await self.cache.aset(key, 0, tags=["number"])
        value = await self.cache.aget(key)
        assert not value.default
        assert value.value == 0
        assert not value.expire_time
        assert value.tags
        assert len(value.tags) == 1
        assert "number" in value.tags
        assert value.key == key

    async def test_getset_expire(self):
        key = 0
        assert await self.cache.aset(key, 0, expire=0.1)
        await anyio.lowlevel.checkpoint()
        assert not (await self.cache.aget(key)).default
        await anyio.sleep(0.1)
        assert (await self.cache.aget(key)).default

    @pytest.mark.parametrize(
        "value",
        [
            None,
            pytest.param((None,) * 2**20, id="tuple"),
            1234,
            pytest.param(2**512, id="big_int"),
            56.78,
            "hello",
            pytest.param("hello" * 2**20, id="big_str"),
            b"world",
            pytest.param(b"world" * 2**20, id="big_bytes"),
        ],
    )
    async def test_getsetdel(self, value):
        key = 0
        assert len(self.origin_cache) == 0
        assert await self.cache.aset(key, value)
        assert len(self.origin_cache) == 1
        assert (await self.cache.aget(key)).value == value
        assert await self.cache.adelete(key)
        assert len(self.origin_cache) == 0
        assert (await self.cache.aget(key)).default

    async def test_getset_tags(self):
        assert await self.cache.aset(0, 0, tags="tag1")
        assert await self.cache.aset(1, 1, tags=["tag2"])
        assert await self.cache.aset(2, 2, tags=["tag1", "tag2"])

        container = await self.cache.aget(0)
        assert not container.default
        assert container.tags
        assert len(container.tags) == 1
        assert "tag1" in container.tags

        container = await self.cache.aget(1)
        assert not container.default
        assert container.tags
        assert len(container.tags) == 1
        assert "tag2" in container.tags

        container = await self.cache.aget(2)
        assert not container.default
        assert container.tags
        assert len(container.tags) == 2
        assert "tag1" in container.tags
        assert "tag2" in container.tags

    async def test_get_default(self, uid):
        assert uid not in self.origin_cache
        container = await self.cache.aget(uid, default=uid)
        assert isinstance(container, typed_diskcache.Container)
        assert container.default
        assert container.value == uid

    async def test_clear(self):
        for key in range(10):
            assert await self.cache.aset(key, key)
        assert len(self.origin_cache) == 10
        await self.cache.aclear()
        assert len(self.origin_cache) == 0

    async def test_stats(self, uid):
        self.origin_cache.update_settings(statistics=True)

        stats = await self.cache.astats()
        assert stats.hits == 0
        assert stats.misses == 0
        assert stats == (0, 0)

        assert len(self.origin_cache) == 0
        await self.cache.aget(uid)
        assert (await self.cache.astats()) == (0, 1)
        await self.cache.aget(uid)
        assert (await self.cache.astats()) == (0, 2)

        assert await self.cache.aset(uid, 0)
        await self.cache.aget(uid)
        assert (await self.cache.astats()) == (1, 2)
        await self.cache.aget(uid)
        assert (await self.cache.astats()) == (2, 2)

    @pytest.mark.parametrize("enable", [True, False])
    async def test_stats_enable(self, uid, enable):
        await self.cache.aget(uid)
        assert await self.cache.astats(enable=enable) == (0, 0)
        await self.cache.aget(uid)
        assert await self.cache.aset(uid, 0)
        await self.cache.aget(uid)
        assert await self.cache.astats() == (int(enable), int(enable))

    @pytest.mark.parametrize("reset", [True, False])
    async def test_stats_reset(self, uid, reset):
        self.origin_cache.update_settings(statistics=True)

        await self.cache.aget(uid)
        assert await self.cache.aset(uid, 0)
        await self.cache.aget(uid)
        assert await self.cache.astats(reset=reset) == (1, 1)
        assert await self.cache.astats() == (int(not reset), int(not reset))

    # TODO: test_volume
    # TODO: test_close

    async def test_touch(self):
        key = 0
        expire = 10
        now = time.time()
        assert await self.cache.aset(key, key, expire=expire)
        container = await self.cache.aget(key)
        assert not container.default
        assert container.expire_time
        assert now + expire < container.expire_time < time.time() + expire

        assert await self.cache.atouch(key, expire=None)
        container = await self.cache.aget(key)
        assert not container.default
        assert not container.expire_time

        assert await self.cache.atouch(key, expire=expire)
        container = await self.cache.aget(key)
        assert not container.default
        assert container.expire_time
        assert now + expire < container.expire_time < time.time() + expire

    async def test_add(self):
        key = 0
        assert key not in self.origin_cache
        assert await self.cache.aadd(key, 0)
        assert key in self.origin_cache
        assert self.origin_cache[key].value == 0
        assert not await self.cache.aadd(key, 1)
        assert self.origin_cache[key].value == 0
        assert self.origin_cache.delete(key)
        assert await self.cache.aadd(key, 1)
        assert self.origin_cache[key].value == 1

    async def test_pop(self, uid):
        key = 0
        assert key not in self.origin_cache
        container = await self.cache.apop(key)
        assert container.default
        assert await self.cache.aset(key, uid)
        container = await self.cache.apop(key)
        assert not container.default
        assert container.value == uid
        assert key not in self.origin_cache

    async def test_pop_default(self, uid):
        key = 0
        assert key not in self.origin_cache
        container = await self.cache.apop(key, default=uid)
        assert isinstance(container, typed_diskcache.Container)
        assert container.default
        assert container.value == uid

    @pytest.mark.parametrize(
        ("tags", "method", "expected"),
        [
            (["tag0"], "and", [1, 4, 5, 7]),
            (["tag0", "tag1"], "and", [4, 7]),
            (["tag0", "tag1"], "or", [1, 2, 4, 5, 6, 7]),
        ],
    )
    def test_filter(self, tags, method, expected):
        assert len(self.origin_cache) == 0
        with ThreadPoolExecutor() as pool:
            futures = [
                pool.submit(self.origin_cache.set, index, index, tags=add_tags)
                for index, add_tags in enumerate([
                    [],
                    ["tag0"],
                    ["tag1"],
                    ["tag2"],
                    ["tag0", "tag1"],
                    ["tag0", "tag2"],
                    ["tag1", "tag2"],
                    ["tag0", "tag1", "tag2"],
                ])
            ]
            wait(futures)

        assert len(self.origin_cache) == 8
        select = set(self.origin_cache.filter(tags, method=method))
        assert select == set(expected)

    @pytest.mark.parametrize(
        ("tags", "method", "expected"),
        [
            (["tag0"], "and", [1, 4, 5, 7]),
            (["tag0", "tag1"], "and", [4, 7]),
            (["tag0", "tag1"], "or", [1, 2, 4, 5, 6, 7]),
        ],
    )
    async def test_afilter(self, tags, method, expected):
        assert len(self.origin_cache) == 0
        async with anyio.create_task_group() as task_group:
            for index, add_tags in enumerate([
                [],
                ["tag0"],
                ["tag1"],
                ["tag2"],
                ["tag0", "tag1"],
                ["tag0", "tag2"],
                ["tag1", "tag2"],
                ["tag0", "tag1", "tag2"],
            ]):
                task_group.start_soon(
                    partial(
                        self.origin_cache.aset, index, index, tags=add_tags, retry=True
                    )
                )

        assert len(self.origin_cache) == 8
        select = [x async for x in self.origin_cache.afilter(tags, method=method)]
        assert set(select) == set(expected)

    @pytest.mark.parametrize(("delta", "default"), product([1, 2, 3], [0, 1, 2]))
    async def test_incr(self, delta: int, default: int):
        key = 0
        assert key not in self.origin_cache
        value = await self.cache.aincr(key, delta, default)
        assert value == default + delta
        assert self.origin_cache[key].value == default + delta
        value = await self.cache.aincr(key, delta, default)
        assert value == default + 2 * delta
        assert self.origin_cache[key].value == default + 2 * delta

    async def test_incr_error(self):
        key = 0
        assert key not in self.origin_cache
        with pytest.raises(te.TypedDiskcacheKeyError):
            await self.cache.aincr(key, default=None)

    @pytest.mark.parametrize(("delta", "default"), product([1, 2, 3], [0, 1, 2]))
    async def test_decr(self, delta: int, default: int):
        key = 0
        assert key not in self.origin_cache
        value = await self.cache.adecr(key, delta, default)
        assert value == default - delta
        assert self.origin_cache[key].value == default - delta
        value = await self.cache.adecr(key, delta, default)
        assert value == default - 2 * delta
        assert self.origin_cache[key].value == default - 2 * delta

    async def test_decr_error(self):
        key = 0
        assert key not in self.origin_cache
        with pytest.raises(te.TypedDiskcacheKeyError):
            await self.cache.adecr(key, default=None)

    # TODO: test_evict

    async def test_expire(self):
        key = 0
        now = time.time()
        assert await self.cache.aset(key, 0, expire=100)
        count = await self.cache.aexpire()
        assert count == 0
        assert key in self.origin_cache
        count = await self.cache.aexpire(now + 200)
        assert count == 1
        assert key not in self.origin_cache

    # TODO: test_cull
    # TODO: test_push
    # TODO: test_pull
    # TODO: test_peek
    # TODO: test_peekitem
    # TODO: test_check

    def test_iterkeys(self):
        iter_type = set if self.cache_type == "fanoutcache" else list
        assert len(self.origin_cache) == 0
        for key in range(10):
            self.origin_cache[key] = key

        assert iter_type(self.origin_cache.iterkeys()) == iter_type(range(10))
        assert iter_type(self.origin_cache.iterkeys(reverse=True)) == iter_type(
            range(9, -1, -1)
        )

    async def test_aiterkeys(self):
        iter_type = set if self.cache_type == "fanoutcache" else list
        assert len(self.origin_cache) == 0
        for key in range(10):
            await self.cache.aset(key, key)

        keys = [key async for key in self.origin_cache.aiterkeys()]
        assert iter_type(keys) == iter_type(range(10))
        keys = [key async for key in self.origin_cache.aiterkeys(reverse=True)]
        assert iter_type(keys) == iter_type(range(9, -1, -1))

    # TODO: test_update_settings
