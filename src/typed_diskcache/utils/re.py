from __future__ import annotations

import re
from os import linesep

__all__ = ["camel_to_snake"]

RE_SNAKE_0_0 = re.compile(r"(.)([A-Z][a-z]+)")
RE_SNAKE_0_1 = r"\1_\2"
RE_SNAKE_1_0 = re.compile(r"__([A-Z])")
RE_SNAKE_1_1 = r"_\1"
RE_SNAKE_2_0 = re.compile(r"([a-z0-9])([A-Z])")
RE_SNAKE_2_1 = r"\1_\2"

RE_ESCAPE = re.compile(r'\\([n\'"]{1})')
RE_COMMENT = re.compile(
    rf"(\".*?\"|\'.*?\')|(/\*.*?\*/|--[^{linesep}]*$)", re.MULTILINE | re.DOTALL
)


def camel_to_snake(name: str) -> str:
    """camel case to snake case

    https://stackoverflow.com/questions/1175208
    elegant-python-function-to-convert-camelcase-to-snake-case

    Args:
        name (str): camel case string

    Returns:
        str: snake case string
    """
    name = RE_SNAKE_0_0.sub(RE_SNAKE_0_1, name)
    name = RE_SNAKE_1_0.sub(RE_SNAKE_1_1, name)
    return RE_SNAKE_2_0.sub(RE_SNAKE_2_1, name).lower()
