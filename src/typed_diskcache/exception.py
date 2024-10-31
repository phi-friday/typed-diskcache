from __future__ import annotations

__all__ = [
    "TypedDiskcacheError",
    "TypedDiskcacheKeyError",
    "TypedDiskcacheValueError",
    "TypedDiskcacheTypeError",
    "TypedDiskcacheIndexError",
    "TypedDiskcacheNotImplementedError",
    "TypedDiskcacheOSError",
    "TypedDiskcacheFileNotFoundError",
    "TypedDiskcacheTimeoutError",
    "TypedDiskcacheRuntimeError",
    "TypedDiskcacheWarning",
    "TypedDiskcacheUnknownFileWarning",
    "TypedDiskcacheEmptyDirWarning",
]


class TypedDiskcacheError(Exception):
    """typed-diskcache base error"""


class TypedDiskcacheKeyError(KeyError, TypedDiskcacheError):
    """typed-diskcache key error"""


class TypedDiskcacheValueError(ValueError, TypedDiskcacheError):
    """typed-diskcache value error"""


class TypedDiskcacheTypeError(TypeError, TypedDiskcacheError):
    """typed-diskcache type error"""


class TypedDiskcacheIndexError(IndexError, TypedDiskcacheError):
    """typed-diskcache index error"""


class TypedDiskcacheNotImplementedError(NotImplementedError, TypedDiskcacheError):
    """typed-diskcache implement error"""


class TypedDiskcacheOSError(OSError, TypedDiskcacheError):
    """typed-diskcache os error"""


class TypedDiskcacheFileNotFoundError(FileNotFoundError, TypedDiskcacheOSError):
    """typed-diskcache File not found error."""


class TypedDiskcacheTimeoutError(TimeoutError, TypedDiskcacheError):
    """typed-diskcache timeout error."""


class TypedDiskcacheRuntimeError(RuntimeError, TypedDiskcacheError):
    """typed-diskcache runtime error."""


class TypedDiskcacheWarning(UserWarning):
    """typed-diskcache warning."""


class TypedDiskcacheUnknownFileWarning(TypedDiskcacheWarning):
    """typed-diskcache unknown file warning."""


class TypedDiskcacheEmptyDirWarning(TypedDiskcacheWarning):
    """typed-diskcache empty directory warning."""
