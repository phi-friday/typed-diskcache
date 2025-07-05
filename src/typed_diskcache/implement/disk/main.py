from __future__ import annotations

import codecs
import io
import os
import struct
import zlib
from pathlib import Path
from typing import TYPE_CHECKING, Any

import cloudpickle
from typing_extensions import override

from typed_diskcache import exception as te
from typed_diskcache.core.const import DISK_DEFAULT_MIN_SIZE, UNKNOWN
from typed_diskcache.core.context import context
from typed_diskcache.core.types import CacheMode
from typed_diskcache.implement.disk import utils as disk_utils
from typed_diskcache.interface.disk import DiskProtocol
from typed_diskcache.log import get_logger
from typed_diskcache.utils.dependency import validate_installed

if TYPE_CHECKING:
    from collections.abc import Mapping
    from os import PathLike


__all__ = ["Disk"]

logger = get_logger()


class Disk(DiskProtocol):
    """Cache key and value serialization for SQLite database and files.

    Args:
        directory: directory for cache
        min_file_size: minimum size for file use. Default is 32kb.
        **kwargs: additional keyword arguments.
            These arguments are not used directly in this class,
            but are added to prevent errors in inherited classes.
    """

    def __init__(
        self,
        directory: str | PathLike[str],
        min_file_size: int = DISK_DEFAULT_MIN_SIZE,
        **kwargs: Any,  # noqa: ARG002
    ) -> None:
        self.directory = directory
        self.min_file_size = min_file_size

    @override
    def __getstate__(self) -> Mapping[str, Any]:
        return {"directory": str(self.directory), "min_file_size": self.min_file_size}

    @override
    def __setstate__(self, state: Mapping[str, Any]) -> None:
        self.directory = state["directory"]
        self.min_file_size = state["min_file_size"]

    @property
    @override
    def directory(self) -> Path:
        return self._directory

    @directory.setter
    @override
    def directory(self, value: str | PathLike[str]) -> None:
        self._directory = Path(value).resolve()

    @override
    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"{str(self.directory)!r}, "
            f"min_file_size={self.min_file_size!r}"
            ")"
        )

    @override
    def hash(self, key: Any) -> int:
        mask = 0xFFFFFFFF
        disk_key: bytes | str | int | float
        disk_key, _ = self.put(key)

        if isinstance(disk_key, bytes):
            return zlib.adler32(disk_key) & mask
        if isinstance(disk_key, str):
            return zlib.adler32(disk_key.encode("utf-8")) & mask
        if isinstance(disk_key, int):
            return disk_key % mask
        return zlib.adler32(struct.pack("!d", disk_key)) & mask

    @context
    @override
    def put(self, key: Any) -> tuple[Any, bool]:
        if isinstance(key, bytes):
            return key, True
        data = cloudpickle.dumps(key)
        return data, False

    @context
    @override
    def get(self, key: Any, *, raw: bool) -> Any:
        if raw:
            return key
        return cloudpickle.loads(key)

    @context
    @override
    def prepare(self, value: Any, *, key: Any = UNKNOWN) -> Path | None:
        if value is None:
            logger.debug("Maybe storing null value")
            return None
        if isinstance(value, str):
            if len(value) < self.min_file_size:
                logger.debug("Maybe storing raw value(string)")

            full_path = self.filename(key, value)
            filename = full_path.relative_to(self.directory)
            logger.debug("Maybe storing text value to `%s`", filename)
            return full_path
        if isinstance(value, bytes):
            if len(value) < self.min_file_size:
                logger.debug("Maybe storing raw value(bytes)")
                return None
            full_path = self.filename(key, value)
            filename = full_path.relative_to(self.directory)
            logger.debug("Maybe storing binary value to `%s`", filename)
            return full_path

        full_path = self.filename(key, value)
        filename = full_path.relative_to(self.directory)
        logger.debug("Maybe store pickled value to `%s`", filename)
        return full_path

    @context
    @override
    def store(  # noqa: PLR0911
        self, value: Any, *, key: Any = UNKNOWN, filepath: Path | None = None
    ) -> tuple[int, CacheMode, str | None, bytes | None]:
        if value is None:
            logger.debug("Storing null value")
            return 0, CacheMode.NONE, None, None
        if isinstance(value, str):
            # str => raw(bytes) | text(file)
            if len(value) < self.min_file_size:
                logger.debug("Storing raw value(string)")
                return 0, CacheMode.TEXT, None, value.encode()

            full_path = disk_utils.ensure_filepath(self, key, value, filepath)
            filename = full_path.relative_to(self.directory)
            logger.debug("Storing text value to `%s`", filename)
            disk_utils.write(full_path, io.StringIO(value), "x", "UTF-8")
            size = full_path.stat().st_size
            return size, CacheMode.TEXT, str(filename), None

        if isinstance(value, bytes):
            # bytes => raw(bytes) | binary(file)
            if len(value) < self.min_file_size:
                logger.debug("Storing raw value(bytes)")
                return 0, CacheMode.BINARY, None, value

            full_path = disk_utils.ensure_filepath(self, key, value, filepath)
            filename = full_path.relative_to(self.directory)
            logger.debug("Storing binary value to `%s`", filename)
            disk_utils.write(full_path, io.BytesIO(value), "xb")
            size = full_path.stat().st_size
            return size, CacheMode.BINARY, str(filename), None

        # others => pickled(bytes) | binary(file)
        result = cloudpickle.dumps(value)
        if len(result) < self.min_file_size:
            logger.debug("Storing pickled value")
            return 0, CacheMode.PICKLE, None, result
        logger.debug(
            "Value size %d is greater than min_file_size %d",
            len(result),
            self.min_file_size,
        )

        full_path = disk_utils.ensure_filepath(self, key, value, filepath)
        filename = full_path.relative_to(self.directory)
        logger.debug("Storing pickled value to `%s`", filename)
        disk_utils.write(full_path, io.BytesIO(result), "xb")
        return len(result), CacheMode.PICKLE, str(filename), None

    @context
    @override
    async def astore(  # noqa: PLR0911
        self, value: Any, *, key: Any = UNKNOWN, filepath: Path | None = None
    ) -> tuple[int, CacheMode, str | None, bytes | None]:
        if value is None:
            logger.debug("Storing null value")
            return 0, CacheMode.NONE, None, None
        if isinstance(value, str):
            # str => raw(bytes) | text(file)
            if len(value) < self.min_file_size:
                logger.debug("Storing raw value(string)")
                return 0, CacheMode.TEXT, None, value.encode()

            full_path = disk_utils.ensure_filepath(self, key, value, filepath)
            filename = full_path.relative_to(self.directory)
            logger.debug("Storing text value to `%s`", filename)
            await disk_utils.async_write(full_path, io.StringIO(value), "x", "UTF-8")
            size = full_path.stat().st_size
            return size, CacheMode.TEXT, str(filename), None

        if isinstance(value, bytes):
            # bytes => raw(bytes) | binary(file)
            if len(value) < self.min_file_size:
                logger.debug("Storing raw value(bytes)")
                return 0, CacheMode.BINARY, None, value

            full_path = disk_utils.ensure_filepath(self, key, value, filepath)
            filename = full_path.relative_to(self.directory)
            logger.debug("Storing binary value to `%s`", filename)
            await disk_utils.async_write(full_path, io.BytesIO(value), "xb")
            size = full_path.stat().st_size
            return size, CacheMode.BINARY, str(filename), None

        # others => pickled(bytes) | binary(file)
        result = cloudpickle.dumps(value)
        if len(result) < self.min_file_size:
            logger.debug("Storing pickled value")
            return 0, CacheMode.PICKLE, None, result
        logger.debug(
            "Value size %d is greater than min_file_size %d",
            len(result),
            self.min_file_size,
        )

        full_path = disk_utils.ensure_filepath(self, key, value, filepath)
        filename = full_path.relative_to(self.directory)
        logger.debug("Storing pickled value to `%s`", filename)
        await disk_utils.async_write(full_path, io.BytesIO(result), "xb")
        return len(result), CacheMode.PICKLE, str(filename), None

    @context
    @override
    def fetch(  # noqa: PLR0911
        self, *, mode: CacheMode, filename: str | PathLike[str] | None, value: Any
    ) -> Any:
        if mode == CacheMode.NONE:
            logger.debug("Fetching null value")
            return None
        if mode == CacheMode.TEXT:
            if filename is None:
                logger.debug("Fetching text value")
                return str(value, "utf-8")
            logger.debug("Fetching text value from `%s`", filename)
            with (self.directory / filename).open("r", encoding="UTF-8") as reader:
                return reader.read()
        if mode == CacheMode.BINARY:
            if filename is None:
                logger.debug("Fetching binary value")
                return value
            logger.debug("Fetching binary value from `%s`", filename)
            with (self.directory / filename).open("rb") as reader:
                return reader.read()
        if mode == CacheMode.PICKLE:
            if filename is None:
                logger.debug("Fetching pickled value")
                return cloudpickle.loads(value)
            logger.debug("Fetching pickled value from `%s`", filename)
            with (self.directory / filename).open("rb") as reader:
                return cloudpickle.load(reader)

        error_msg = f"Incorrect mode `{mode}`"
        raise te.TypedDiskcacheValueError(error_msg)

    @context
    @override
    async def afetch(  # noqa: PLR0911
        self, *, mode: CacheMode, filename: str | PathLike[str] | None, value: Any
    ) -> Any:
        validate_installed("anyio", "Consider installing extra `asyncio`.")
        import anyio  # noqa: PLC0415

        if mode == CacheMode.NONE:
            logger.debug("Fetching null value")
            return None
        if mode == CacheMode.TEXT:
            if filename is None:
                logger.debug("Fetching text value")
                return str(value, "utf-8")
            logger.debug("Fetching text value from `%s`", filename)
            async with await anyio.Path(self.directory / filename).open(
                "r", encoding="UTF-8"
            ) as reader:
                return await reader.read()
        if mode == CacheMode.BINARY:
            if filename is None:
                logger.debug("Fetching binary value")
                return value
            logger.debug("Fetching binary value from `%s`", filename)
            async with await anyio.Path(self.directory / filename).open("rb") as reader:
                return await reader.read()
        if mode == CacheMode.PICKLE:
            if filename is None:
                logger.debug("Fetching pickled value")
                return cloudpickle.loads(value)
            logger.debug("Fetching pickled value from `%s`", filename)
            async with await anyio.Path(self.directory / filename).open("rb") as reader:
                return cloudpickle.loads(await reader.read())

        error_msg = f"Incorrect mode `{mode}`"
        raise te.TypedDiskcacheValueError(error_msg)

    @context
    @override
    def remove(self, file_path: str | PathLike[str]) -> None:
        full_path = self.directory / file_path
        full_dir = full_path.parent

        # Suppress OSError that may occur if two caches attempt to delete the
        # same file or directory at the same time.

        logger.debug("Removing `%s`", full_path)
        try:
            full_path.unlink()
        except OSError as exc:
            logger.error("Failed to remove `%s`, errno: %s", full_path, exc.errno)  # noqa: TRY400

        logger.debug("Removing `%s`", full_dir)
        try:
            full_dir.rmdir()
        except OSError as exc:
            logger.error("Failed to remove `%s`, errno: %s", full_dir, exc.errno)  # noqa: TRY400

    @context
    @override
    async def aremove(self, file_path: str | PathLike[str]) -> None:
        validate_installed("anyio", "Consider installing extra `asyncio`.")
        import anyio  # noqa: PLC0415

        full_path = anyio.Path(self.directory / file_path)
        full_dir = full_path.parent

        # Suppress OSError that may occur if two caches attempt to delete the
        # same file or directory at the same time.

        logger.debug("Removing `%s`", full_path)
        try:
            await full_path.unlink()
        except OSError as exc:
            logger.error("Failed to remove `%s`, errno: %s", full_path, exc.errno)  # noqa: TRY400

        logger.debug("Removing `%s`", full_dir)
        try:
            await full_dir.rmdir()
        except OSError as exc:
            logger.error("Failed to remove `%s`, errno: %s", full_dir, exc.errno)  # noqa: TRY400

    @context
    @override
    def filename(self, key: Any = UNKNOWN, value: Any = UNKNOWN) -> Path:
        hex_name = codecs.encode(os.urandom(16), "hex").decode("utf-8")
        filename = Path(hex_name[:2]) / hex_name[2:4] / f"{hex_name[4:]}.val"
        return self.directory / filename

    @override
    def model_dump(self) -> tuple[str, dict[str, Any]]:
        cls = type(self)
        name = f"{cls.__module__}.{cls.__qualname__}"
        return name, {
            "directory": str(self.directory),
            "min_file_size": self.min_file_size,
        }
