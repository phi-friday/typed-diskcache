from __future__ import annotations

from functools import lru_cache
from importlib.util import find_spec

from typed_diskcache.log import get_logger

__all__ = ["is_installed", "validate_installed"]

logger = get_logger()


@lru_cache
def is_installed(module_name: str) -> bool:
    """Check if a module is installed."""
    return find_spec(module_name) is not None


def validate_installed(
    module_name: str, additional_error_msg: str | None = None
) -> None:
    """Validate if a module is installed."""
    if not is_installed(module_name):
        error_msg = f"Module {module_name} is not installed."
        if additional_error_msg:
            error_msg += "\n" + additional_error_msg
        raise ModuleNotFoundError(error_msg)
