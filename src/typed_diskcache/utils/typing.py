"""
.. data:: StrPath
    :noindex:
    :type: typing.TypeAliasType
    :value: str | os.PathLike[str]

    Type alias for a file path.

    Bound:
        :class:`str` | :class:`os.PathLike[str]`
"""  # noqa: D205

from __future__ import annotations

from os import PathLike
from typing import Literal, Union

from typing_extensions import TypeAlias

StrPath: TypeAlias = Union[str, PathLike[str]]
OpenBinaryModeWriting: TypeAlias = Literal["wb", "bw", "ab", "ba", "xb", "bx"]
OpenTextModeWriting: TypeAlias = Literal[
    "w", "wt", "tw", "a", "at", "ta", "x", "xt", "tx"
]
