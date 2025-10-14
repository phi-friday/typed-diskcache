from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import suppress
from typing import TYPE_CHECKING, Any, Literal, TypeAlias, overload

from typed_diskcache.utils.dependency import validate_installed

if TYPE_CHECKING:
    from pathlib import Path

    from anyio import Path as AnyioPath

    from typed_diskcache.interface.disk import DiskProtocol


__all__ = []

OpenBinaryModeWriting: TypeAlias = Literal["wb", "bw", "ab", "ba", "xb", "bx"]
OpenTextModeWriting: TypeAlias = Literal[
    "w", "wt", "tw", "a", "at", "ta", "x", "xt", "tx"
]


@overload
def write(
    full_path: Path,
    iterator: Iterator[str],
    mode: OpenTextModeWriting,
    encoding: str | None = ...,
) -> int | None: ...
@overload
def write(
    full_path: Path,
    iterator: Iterator[bytes],
    mode: OpenBinaryModeWriting,
    encoding: str | None = ...,
) -> int | None: ...
def write(
    full_path: Path,
    iterator: Iterator[str | bytes],
    mode: OpenTextModeWriting | OpenBinaryModeWriting,
    encoding: str | None = None,
) -> int | None:
    full_dir = full_path.parent

    max_try = 10
    for count in range(1, max_try + 1):
        with suppress(OSError):
            full_dir.mkdir(parents=True)

        try:
            # Another cache may have deleted the directory before
            # the file could be opened.
            writer = full_path.open(mode, encoding=encoding)
        except OSError:
            if count == max_try:
                # Give up after 10 tries to open the file.
                raise
            continue

        with writer:
            size = 0
            for chunk in iterator:
                size += len(chunk)
                writer.write(chunk)
            return size
    return None


@overload
async def async_write(
    full_path: Path | AnyioPath,
    iterator: Iterator[str] | AsyncIterator[str],
    mode: OpenTextModeWriting,
    encoding: str | None = None,
) -> int | None: ...
@overload
async def async_write(
    full_path: Path | AnyioPath,
    iterator: Iterator[bytes] | AsyncIterator[bytes],
    mode: OpenBinaryModeWriting,
    encoding: str | None = None,
) -> int | None: ...
async def async_write(
    full_path: Path | AnyioPath,
    iterator: Iterator[str | bytes] | AsyncIterator[str | bytes],
    mode: OpenTextModeWriting | OpenBinaryModeWriting,
    encoding: str | None = None,
) -> int | None:
    validate_installed("anyio", "Consider installing extra `asyncio`.")
    import anyio  # noqa: PLC0415

    full_path = anyio.Path(full_path)
    full_dir = full_path.parent

    max_try = 10
    for count in range(1, max_try + 1):
        with suppress(OSError):
            await full_dir.mkdir(parents=True)

        try:
            # Another cache may have deleted the directory before
            # the file could be opened.
            writer: anyio.AsyncFile[Any] = await full_path.open(mode, encoding=encoding)
        except OSError:
            if count == max_try:
                # Give up after 10 tries to open the file.
                raise
            continue

        async with writer:
            size = 0
            if isinstance(iterator, AsyncIterator):
                async for chunk in iterator:
                    size += len(chunk)
                    await writer.write(chunk)
            else:
                for chunk in iterator:
                    size += len(chunk)
                    await writer.write(chunk)
            return size
    return None


def ensure_filepath(
    disk: DiskProtocol, key: Any, value: Any, filepath: Path | None
) -> Path:
    if filepath is not None:
        return filepath
    return disk.filename(key, value)
