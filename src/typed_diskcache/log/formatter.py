from __future__ import annotations

import logging

from typing_extensions import override

from typed_diskcache.core.context import log_context, override_context

__all__ = []


class Formatter(logging.Formatter):
    @override
    def format(self, record: logging.LogRecord) -> str:
        context = override_context.get()
        if context is None:
            context = log_context.get()
        record.log_context, record.log_thread = context
        return super().format(record)
