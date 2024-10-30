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
        **kwargs: additional keyword arguments.
            These arguments may not be used directly in this class,
            but are added to prevent errors in inherited classes.
    """

    def __init__(self, directory: str | PathLike[str], **kwargs: Any) -> None: ...
    def __getstate__(self) -> Mapping[str, Any]: ...
    def __setstate__(self, state: Mapping[str, Any]) -> None: ...

    @property
    def directory(self) -> Path:
        """Return the directory for the cache."""
        ...

    @directory.setter
    def directory(self, value: str | PathLike[str]) -> None: ...

    def hash(self, key: Any) -> int:
        """Return the hash value for `key`.

        Args:
            key: key to hash

        Returns:
            hash value
        """
        ...

    def put(self, key: Any) -> tuple[Any, bool]:
        """Convert `key` to a format suitable for storage in the Cache table.

        This method takes a key and converts it into a database-compatible key
        and a boolean indicating whether the key is in its raw form.

        Args:
            key: The key to convert.

        Returns:
            (database key, raw boolean) pair
        """
        ...

    def get(self, key: Any, *, raw: bool) -> Any:
        """Convert fields `key` and `raw` from Cache table to a Python key.

        This method takes a database key and a flag indicating if the key is stored
        in its raw form, and converts them back to the corresponding Python key.

        Args:
            key: The database key to convert.
            raw: A flag indicating if the key is stored in its raw form.

        Returns:
            The corresponding Python key.
        """
        ...

    def prepare(self, value: Any, *, key: Any = ...) -> tuple[Path, Path] | None:
        """Prepare filename and full-path tuple for file storage.

        This method takes a value and an optional key, and prepares a tuple
        containing the filename and the full path for storing the file.

        Args:
            value: The value to store.
            key: The key for the item (optional).

        Returns:
            A tuple containing the filename and full path, or None if preparation fails.
        """
        ...

    def store(
        self, value: Any, *, key: Any = ..., filepath: tuple[Path, Path] | None = ...
    ) -> tuple[int, CacheMode, str | None, bytes | None]:
        """Convert `value` to fields for Cache table.

        This method converts a value into a tuple containing the size, mode,
        filename, and value suitable for storage in the Cache table.

        Args:
            value: The value to store.
            key: The key for the item.
            filepath: A tuple containing the filename and full path.

        Returns:
            (size, mode, filename, value) tuple for Cache table
        """
        ...

    async def astore(
        self, value: Any, *, key: Any = ..., filepath: tuple[Path, Path] | None = ...
    ) -> tuple[int, CacheMode, str | None, bytes | None]:
        """Asynchronously convert `value` to fields for Cache table.

        This method is the asynchronous version of
        [`store`][typed_diskcache.interface.disk.DiskProtocol.store].
        It converts a value into a tuple containing the size, mode, filename, and value
        suitable for storage in the Cache table.

        Args:
            value: The value to store.
            key: The key for the item.
            filepath: A tuple containing the filename and full path.

        Returns:
            (size, mode, filename, value) tuple for Cache table
        """
        ...

    def fetch(
        self, *, mode: CacheMode, filename: str | PathLike[str] | None, value: Any
    ) -> Any:
        """Convert fields from Cache table to a Python value.

        This method converts the fields `mode`, `filename`, and `value` from the Cache
        table back to the corresponding Python value.

        Args:
            mode: The mode of the value (none, binary, text, or pickle).
            filename: The filename of the corresponding value.
            value: The database value.

        Returns:
            The corresponding Python value.
        """
        ...

    async def afetch(
        self, *, mode: CacheMode, filename: str | PathLike[str] | None, value: Any
    ) -> Any:
        """Asynchronously convert fields from Cache table to a Python value.

        This method is the asynchronous version of
        [`fetch`][typed_diskcache.interface.disk.DiskProtocol.fetch].
        It converts the fields `mode`, `filename`, and `value`
        from the Cache table back to the corresponding Python value.

        Args:
            mode: The mode of the value (none, binary, text, or pickle).
            filename: The filename of the corresponding value.
            value: The database value.

        Returns:
            The corresponding Python value.
        """
        ...

    def remove(self, file_path: str | PathLike[str]) -> None:
        """Remove a file given by `file_path`.

        This method is cross-thread and cross-process safe. If an OSError occurs,
        it is suppressed.

        Args:
            file_path: The relative path to the file.
        """
        ...

    async def aremove(self, file_path: str | PathLike[str]) -> None:
        """Asynchronously remove a file given by `file_path`.

        This method is the asynchronous version of
        [`remove`][typed_diskcache.interface.disk.DiskProtocol.remove].
        It is cross-thread and cross-process safe.
        If an OSError occurs, it is suppressed.

        Args:
            file_path: The relative path to the file.
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
            key: key for item.
            value: value for item.

        Returns:
            filename and full-path tuple
        """
        ...

    def model_dump(self) -> tuple[str, dict[str, Any]]:
        """Return the model name and model state.

        This method returns a tuple containing the model name and a dictionary
        representing the model state.

        Returns:
            (model name, model state) tuple
        """
        ...
