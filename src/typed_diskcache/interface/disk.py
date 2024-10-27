from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Mapping
    from os import PathLike
    from pathlib import Path

    from typed_diskcache.core.types import CacheMode


__all__ = ["DiskProtocol"]


@runtime_checkable
class DiskProtocol(Protocol):
    """Cache key and value serialization for SQLite database and files.

    Args:
        directory: directory for cache
        kwargs: additional keyword arguments
    """

    def __init__(self, directory: str | PathLike[str], **kwargs: Any) -> None: ...
    def __getstate__(self) -> Mapping[str, Any]: ...
    def __setstate__(self, state: Mapping[str, Any]) -> None: ...

    @property
    def directory(self) -> Path:
        """Directory for cache."""
        ...

    @directory.setter
    def directory(self, value: str | PathLike[str]) -> None: ...

    def hash(self, key: Any) -> int:
        """Compute portable hash for `key`.

        Args:
            key: key to hash

        Returns:
            hash value
        """
        ...

    def put(self, key: Any) -> tuple[Any, bool]:
        """Convert `key` to fields key and raw for Cache table.

        Args:
            key: key to convert

        Returns:
            (database key, raw boolean) pair
        """
        ...

    def get(self, key: Any, *, raw: bool) -> Any:
        """Convert fields `key` and `raw` from Cache table to key.

        Args:
            key: database key to convert
            raw: flag indicating raw database storage

        Returns:
            corresponding Python key
        """
        ...

    def prepare(self, value: Any, *, key: Any = ...) -> tuple[Path, Path] | None:
        """Prepare filename and full-path tuple for file storage.

        Args:
            value: value to store
            key: key for item

        Returns:
            filename and full-path tuple
        """
        ...

    def store(
        self, value: Any, *, key: Any = ..., filepath: tuple[Path, Path] | None = ...
    ) -> tuple[int, CacheMode, str | None, bytes | None]:
        """Convert `value` to fields size, mode, filename, and value for Cache table.

        Args:
            value: value to store
            key: key for item. Defaults to UNKNOWN.
            filepath: filename and full-path tuple. Defaults to None.

        Returns:
            (size, mode, filename, value) tuple for Cache table
        """
        ...

    async def astore(
        self, value: Any, *, key: Any = ..., filepath: tuple[Path, Path] | None = ...
    ) -> tuple[int, CacheMode, str | None, bytes | None]:
        """Convert `value` to fields size, mode, filename, and value for Cache table.

        Asynchronous version of `store`.

        Args:
            value: value to store
            key: key for item. Defaults to UNKNOWN.
            filepath: filename and full-path tuple. Defaults to None.

        Returns:
            (size, mode, filename, value) tuple for Cache table
        """
        ...

    def fetch(
        self, *, mode: CacheMode, filename: str | PathLike[str] | None, value: Any
    ) -> Any:
        """Convert fields `mode`, `filename`, and `value` from Cache table to value.

        Args:
            mode: value mode none, binary, text, or pickle
            filename: filename of corresponding value
            value: database value

        Returns:
            corresponding Python value
        """
        ...

    async def afetch(
        self, *, mode: CacheMode, filename: str | PathLike[str] | None, value: Any
    ) -> Any:
        """Convert fields `mode`, `filename`, and `value` from Cache table to value.

        Asynchronous version of `fetch`.

        Args:
            mode: value mode none, binary, text, or pickle
            filename: filename of corresponding value
            value: database value

        Returns:
            corresponding Python value
        """
        ...

    def remove(self, file_path: str | PathLike[str]) -> None:
        """Remove a file given by `file_path`.

        This method is cross-thread and cross-process safe.
        If an OSError occurs, it is suppressed.

        Args:
            file_path: relative path to file
        """
        ...

    async def aremove(self, file_path: str | PathLike[str]) -> None:
        """Remove a file given by `file_path`.

        This method is cross-thread and cross-process safe.
        If an OSError occurs, it is suppressed.

        Asynchronous version of `remove`.

        Args:
            file_path: relative path to file
        """
        ...

    def filename(self, key: Any = ..., value: Any = ...) -> tuple[Path, Path]:
        """Return filename and full-path tuple for file storage.

        Filename will be a randomly generated 28 character hexadecimal string
        with ".val" suffixed. Two levels of sub-directories will be used to
        reduce the size of directories. On older filesystems, lookups in
        directories with many files may be slow.

        The default implementation ignores the `key` and `value` parameters.

        Args:
            key: key for item. Defaults to UNKNOWN.
            value: value for item. Defaults to UNKNOWN.

        Returns:
            filename and full-path tuple
        """
        ...

    def model_dump(self) -> tuple[str, dict[str, Any]]:
        """Return the model name and model state."""
        ...
