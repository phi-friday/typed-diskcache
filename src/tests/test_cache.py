from __future__ import annotations

import inspect
import pickle
from collections.abc import Callable
from contextlib import suppress
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
    ("cache_type", "is_async"), list(product(["cache", "fanoutcache"], [True, False]))
)
class TestCache:
    cache_type: Literal["cache", "fanoutcache"]
    origin_cache: interface.CacheProtocol
    cache: interface.CacheProtocol

    @pytest.fixture(autouse=True)
    def _init(self, cache_directory, cache_type, is_async):  # noqa: ANN202
        if cache_type == "cache":
            self.cache_type = "cache"
            self.origin_cache = typed_diskcache.Cache(cache_directory)
        elif cache_type == "fanoutcache":
            self.cache_type = "fanoutcache"
            self.origin_cache = typed_diskcache.FanoutCache(cache_directory)
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
            (None,) * 2**20,
            1234,
            2**512,
            56.78,
            "hello",
            "hello" * 2**20,
            b"world",
            b"world" * 2**20,
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
            (None,) * 2**20,
            1234,
            2**512,
            56.78,
            "hello",
            "hello" * 2**20,
            b"world",
            b"world" * 2**20,
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
