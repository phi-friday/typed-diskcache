from __future__ import annotations

from typed_diskcache.core.types import Container
from typed_diskcache.implement import (
    AsyncLock,
    AsyncRLock,
    AsyncSemaphore,
    Cache,
    Disk,
    FanoutCache,
    SyncLock,
    SyncRLock,
    SyncSemaphore,
)

__all__ = [
    "AsyncLock",
    "AsyncRLock",
    "AsyncSemaphore",
    "Cache",
    "Container",
    "Disk",
    "FanoutCache",
    "SyncLock",
    "SyncRLock",
    "SyncSemaphore",
]

__version__: str


def __getattr__(name: str) -> object:
    if name == "__version__":  # pragma: no cover
        from importlib.metadata import version  # noqa: PLC0415

        _version = globals()["__version__"] = version("typed-diskcache")
        return _version
    error_msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(error_msg)
