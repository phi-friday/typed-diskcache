# pyright: reportMissingModuleSource=false
from __future__ import annotations

import logging
import sys
from functools import lru_cache
from logging.config import dictConfig
from pathlib import Path
from typing import Any

from typed_diskcache.core.const import DEFAULT_LOG_LEVEL

if sys.version_info >= (3, 11):
    import tomllib as toml
else:
    import tomli as toml

__all__ = ["get_logger"]


@lru_cache
def _load_config() -> dict[str, Any]:
    file = Path(__file__).with_name("log.toml")
    with file.open("rb") as f:
        return toml.load(f)


@lru_cache
def _setup_logging() -> None:
    config = _load_config()
    default = config["default"]
    config["config"]["loggers"][default]["level"] = (
        int(DEFAULT_LOG_LEVEL) if DEFAULT_LOG_LEVEL.isdigit() else DEFAULT_LOG_LEVEL
    )
    dictConfig(config["config"])


@lru_cache
def _default_logger_name() -> str:
    _setup_logging()
    config = _load_config()
    return config["default"]


def get_logger() -> logging.Logger:
    """Get the default logger."""
    name = _default_logger_name()
    return logging.getLogger(name)
