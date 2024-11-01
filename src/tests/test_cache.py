from __future__ import annotations

import inspect
from collections.abc import Callable
from contextlib import suppress
from itertools import product
from typing import Any

import anyio
import anyio.lowlevel
import pytest

import typed_diskcache
from typed_diskcache import interface
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
    ("cache_type", "is_async"), list(product(["cache", "fanout_cache"], [True, False]))
)
class TestCache:
    origin_cache: interface.CacheProtocol
    cache: interface.CacheProtocol

    @pytest.fixture(autouse=True)
    def _init(self, cache_directory, cache_type, is_async):  # noqa: ANN202
        if cache_type == "cache":
            self.origin_cache = typed_diskcache.Cache(cache_directory)
        elif cache_type == "fanout_cache":
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

    def test_cache_settings(self):
        settings = self.cache.settings
        default_settings = Settings()
        exclude = {"serialized_disk", "size_limit"}
        assert settings.model_dump(exclude=exclude) == default_settings.model_dump(
            exclude=exclude
        )

    async def test_getset(self):
        uid = 0
        value = await self.cache.aget(uid)
        assert isinstance(value, typed_diskcache.Container)
        assert value.default
        assert value.value is None
        assert not value.expire_time
        assert not value.tags
        assert not value.key

        assert (await self.cache.aget(uid, "dne")).value == "dne"
        assert (await self.cache.aget(uid, {})).value == {}

        assert await self.cache.aset(uid, 0, tags=["number"])
        value = await self.cache.aget(uid)
        assert not value.default
        assert value.value == 0
        assert not value.expire_time
        assert value.tags
        assert len(value.tags) == 1
        assert "number" in value.tags
        assert value.key == uid

    async def test_getset_expire(self):
        uid = 0
        assert await self.cache.aset(uid, 0, expire=0.1)
        await anyio.lowlevel.checkpoint()
        assert not (await self.cache.aget(uid)).default
        await anyio.sleep(0.1)
        assert (await self.cache.aget(uid)).default

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
        uid = 0
        assert len(self.origin_cache) == 0
        assert await self.cache.aset(uid, value)
        assert len(self.origin_cache) == 1
        assert (await self.cache.aget(uid)).value == value
        assert await self.cache.adelete(uid)
        assert len(self.origin_cache) == 0
        assert (await self.cache.aget(uid)).default
