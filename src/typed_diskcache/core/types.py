from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from functools import cached_property
from typing import Annotated, Any, Generic, Literal, NamedTuple, final

from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import LiteralString, TypeVar, override

if sys.version_info >= (3, 11):
    from enum import IntEnum, StrEnum
else:
    from enum import Enum, IntEnum

    class StrEnum(str, Enum):
        @override
        def __str__(self) -> str:
            return self.value


__all__ = [
    "Constant",
    "SettingsKey",
    "EvictionPolicy",
    "CacheMode",
    "MetadataKey",
    "Stats",
    "FilterMethod",
    "FilterMethodLiteral",
    "QueueSide",
    "QueueSideLiteral",
    "Container",
]

_T = TypeVar("_T", infer_variance=True)
_LiteralT = TypeVar("_LiteralT", bound=LiteralString, infer_variance=True)
_UTC = timezone(timedelta(0))


class Constant(tuple[_LiteralT], Generic[_LiteralT]):
    """Pretty display of immutable constant."""

    __slots__ = ()

    @override
    def __new__(cls, name: _LiteralT) -> Constant[_LiteralT]:
        return tuple.__new__(cls, (name,))

    @override
    def __repr__(self) -> str:
        return f"{self[0]}"


class MetadataKey(StrEnum):
    """DiskCache metadata keys."""

    COUNT = "count"
    SIZE = "size"
    HITS = "hits"
    MISSES = "misses"


class SettingsKey(StrEnum):
    """DiskCache settings keys."""

    UNKNOWN = "unknown"
    ### DiskCache settings
    STATISTICS = "statistics"
    EVICTION_POLICY = "eviction_policy"
    SIZE_LIMIT = "size_limit"
    CULL_LIMIT = "cull_limit"
    SERIALIZED_DISK = "serialized_disk"
    ### SQLite pragma settings
    SQLITE_AUTO_VACUUM = "sqlite_auto_vacuum"
    SQLITE_CACHE_SIZE = "sqlite_cache_size"
    SQLITE_JOURNAL_MODE = "sqlite_journal_mode"
    SQLITE_MMAP_SIZE = "sqlite_mmap_size"
    SQLITE_SYNCHRONOUS = "sqlite_synchronous"


class EvictionPolicy(StrEnum):
    """DiskCache eviction policies."""

    NONE = "none"
    LEAST_RECENTLY_STORED = "least-recently-stored"
    LEAST_RECENTLY_USED = "least-recently-used"
    LEAST_FREQUENTLY_USED = "least-frequently-used"


class CacheMode(IntEnum):
    """DiskCache value modes."""

    NONE = 0
    BINARY = 1
    TEXT = 2
    PICKLE = 3


class FilterMethod(StrEnum):
    """DiskCache filter methods."""

    AND = "and"
    OR = "or"


FilterMethodLiteral = Literal["and", "or"]


class QueueSide(StrEnum):
    """DiskCache queue sides."""

    FRONT = "front"
    BACK = "back"


QueueSideLiteral = Literal["front", "back"]


class Stats(NamedTuple):
    """DiskCache statistics."""

    hits: int
    misses: int


@final
class Container(BaseModel, Generic[_T]):
    """DiskCache value container."""

    model_config = ConfigDict(frozen=True)

    key: Annotated[Any, Field(repr=False)] = None
    """The key associated with the value."""
    value: Annotated[_T, Field(repr=False)]
    """The value to store."""
    default: bool
    """Whether the value is the default value."""
    expire_time: float | None = None
    """The time in seconds since the epoch when the value expires."""
    tags: frozenset[str] | None = None
    """The tags associated with the value."""

    @cached_property
    def expire_datetime(self) -> datetime | None:
        """Get expire time as datetime."""
        if self.expire_time is not None:
            return datetime.fromtimestamp(self.expire_time, tz=_UTC)
        return None
