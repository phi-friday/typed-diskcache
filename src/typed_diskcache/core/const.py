from __future__ import annotations

import sys
import threading
from os import getenv
from typing import Literal

from typed_diskcache.core.types import Constant

__all__ = []

DBNAME = "cache.db"
"""The default name of the SQLite database file."""
CONNECTION_BEGIN_INFO_KEY = "is_begin_immediate"
"""The key to store the information about the connection being in immediate mode."""
DISK_DEFAULT_MIN_SIZE = 2**15  # 32kb
"""
The default minimum size of the disk cache in bytes.
If the size of the value is greater than this, it will be stored in the file system.
"""
REVISION_MAXIMA = 999
"""The maximum value of the revision number."""
QUEUE_KEY_MINIMA = 0
"""The minimum value of the queue key."""
QUEUE_KEY_MAXIMA = 999999999999999
"""The maximum value of the queue key."""
QUEUE_KEY_DEFAULT = 500000000000000
"""The default value of the queue key."""
SPIN_LOCK_SLEEP = 0.001
"""The time to sleep in the spin lock."""
DEFAULT_LOCK_TIMEOUT = 10
"""The default lock timeout."""
DEFAULT_SIZE_LIMIT = 2**30  # 1gb
"""The default size limit of the cache in bytes."""


ENOVAL: Constant[Literal["ENOVAL"]] = Constant("ENOVAL")
UNKNOWN: Constant[Literal["UNKNOWN"]] = Constant("UNKNOWN")
DEFAULT_LOG_THREAD_KEY = "_TYPED_DISKCACHE_LOG_THREAD"
DEFAULT_LOG_CONTEXT_KEY = "_TYPED_DISKCACHE_LOG_CONTEXT"
DEFAULT_LOG_LEVEL_KEY = "TYPED_DISKCACHE_LOG_LEVEL"
DEFAULT_LOG_THREAD = (
    int(_x)
    if (_x := getenv(DEFAULT_LOG_THREAD_KEY, "")).isdigit()
    else threading.get_native_id()
)
DEFAULT_LOG_CONTEXT = getenv(DEFAULT_LOG_CONTEXT_KEY, "main")
DEFAULT_LOG_LEVEL = getenv(DEFAULT_LOG_LEVEL_KEY, "info").upper()
IS_FREE_THREAD = "free-threading" in sys.version and sys.version_info >= (3, 13)
