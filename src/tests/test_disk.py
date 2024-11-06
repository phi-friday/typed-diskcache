from __future__ import annotations

from typing import Literal

import pytest

import typed_diskcache
from tests.base import AsyncWrapper
from typed_diskcache import interface

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

    @pytest.mark.only
    def test_is_disk(self):
        assert isinstance(self.origin_disk, typed_diskcache.Disk)
