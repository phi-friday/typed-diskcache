from __future__ import annotations

from pathlib import Path
from typing import Literal

import pytest

import typed_diskcache
from tests.base import AsyncWrapper, value_params
from typed_diskcache import interface
from typed_diskcache.core.types import CacheMode

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    ("disk_type", "is_async"),
    [
        pytest.param("disk", True, id="disk-async"),
        pytest.param("disk", False, id="disk-sync"),
    ],
)
class TestDisk:
    disk_type: Literal["disk"]
    origin_disk: interface.DiskProtocol
    disk: interface.DiskProtocol

    @pytest.fixture(autouse=True)
    def _init(self, cache_directory, disk_type, is_async):  # noqa: ANN202
        if disk_type == "disk":
            self.disk_type = "disk"
            self.origin_disk = typed_diskcache.Disk(cache_directory)
        else:
            error_msg = f"Unknown disk type: {disk_type!r}"
            raise RuntimeError(error_msg)
        self.disk = AsyncWrapper(self.origin_disk, is_async=is_async)

    def test_is_disk(self):
        assert isinstance(self.origin_disk, typed_diskcache.Disk)

    def test_attribute(self):
        assert isinstance(self.origin_disk.directory, Path)

    def test_model_dump(self):
        data = self.origin_disk.model_dump()
        assert isinstance(data, tuple)
        assert len(data) == 2
        name, args = data
        assert isinstance(name, str)
        assert (
            name
            == type(self.origin_disk).__module__
            + "."
            + type(self.origin_disk).__qualname__
        )
        assert "directory" in args
        assert isinstance(args["directory"], str)
        assert args["directory"] == str(self.origin_disk.directory)

    @value_params
    def test_hash(self, value):
        value = self.origin_disk.hash(value)
        assert isinstance(value, int)

    @value_params
    def test_put(self, value):
        key, raw = self.origin_disk.put(value)
        assert isinstance(key, (bytes, str, int, float))
        assert isinstance(raw, bool)
        assert raw is isinstance(value, bytes)

    @value_params
    def test_get(self, value):
        key, raw = self.origin_disk.put(value)
        result = self.origin_disk.get(key, raw=raw)
        assert result == value

    @value_params
    @pytest.mark.parametrize("key", [True, False])
    def test_prepare(self, value, key):
        prepare_params = {}
        if key:
            prepare_params["key"] = value

        file_path = self.origin_disk.prepare(value, **prepare_params)
        if value is None:
            assert file_path is None
            return

        if file_path is None:
            # TODO: Implement this test
            pytest.skip("Not yet implemented")

        assert file_path is not None
        assert isinstance(file_path, Path)

    @value_params
    @pytest.mark.parametrize("key", [True, False])
    @pytest.mark.parametrize("filepath", [True, False])
    async def test_store(self, value, key, filepath):
        params = {}
        if key:
            params["key"] = value
        if filepath:
            params["filepath"] = self.origin_disk.prepare(value, **params)

        size, mode, filename, db_value = await self.disk.astore(value, **params)

        assert isinstance(size, int)
        assert isinstance(mode, CacheMode)
        assert filename is None or isinstance(filename, str)
        assert db_value is None or isinstance(db_value, bytes)
        assert any((filename is None, db_value is None))

    @value_params
    @pytest.mark.parametrize("key", [True, False])
    @pytest.mark.parametrize("filepath", [True, False])
    async def test_fetch(self, value, key, filepath):
        params = {}
        if key:
            params["key"] = value
        if filepath:
            params["filepath"] = self.origin_disk.prepare(value, **params)

        _, mode, filename, db_value = await self.disk.astore(value, **params)
        fetch = await self.disk.afetch(mode=mode, filename=filename, value=db_value)

        assert fetch == value

    @pytest.mark.parametrize(
        "value",
        [
            pytest.param((None,) * 2**20, id="tuple"),
            pytest.param("hello" * 2**20, id="long_str"),
            pytest.param(b"world" * 2**20, id="long_bytes"),
        ],
    )
    @pytest.mark.parametrize("key", [True, False])
    @pytest.mark.parametrize("filepath", [True, False])
    async def test_remove(self, value, key, filepath):
        params = {}
        if key:
            params["key"] = value
        if filepath:
            params["filepath"] = self.origin_disk.prepare(value, **params)
        _, _, filename, _ = await self.disk.astore(value, **params)

        assert filename
        file = self.origin_disk.directory / filename
        assert file.exists()

        await self.disk.aremove(filename)
        assert not file.exists()

    @value_params
    @pytest.mark.parametrize("key", [True, False])
    def test_filename(self, value, key):
        params = {}
        if key:
            params["key"] = value

        filename = self.origin_disk.filename(value=value, **params)
        assert isinstance(filename, Path)
        assert filename.is_relative_to(self.origin_disk.directory)
