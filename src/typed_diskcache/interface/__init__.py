from __future__ import annotations

from typed_diskcache.interface.cache import CacheProtocol
from typed_diskcache.interface.disk import DiskProtocol
from typed_diskcache.interface.sync import (
    AsyncLockProtocol,
    AsyncSemaphoreProtocol,
    SyncLockProtocol,
    SyncSemaphoreProtocol,
)

__all__ = [
    "AsyncLockProtocol",
    "AsyncSemaphoreProtocol",
    "CacheProtocol",
    "DiskProtocol",
    "SyncLockProtocol",
    "SyncSemaphoreProtocol",
]
