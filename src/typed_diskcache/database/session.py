from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession as SqlalchemyAsyncSession
from sqlalchemy.orm import Session as SqlalchemySession
from typing_extensions import override

from typed_diskcache.core.context import log_context, override_context

__all__ = []


class Session(SqlalchemySession):
    @override
    def close(self) -> None:
        context = override_context.get()
        if context is not None:
            log_context_value = log_context.get()
            if log_context_value != context:
                return
        super().close()


class AsyncSession(SqlalchemyAsyncSession):
    @override
    async def close(self) -> None:
        context = override_context.get()
        if context is not None:
            log_context_value = log_context.get()
            if log_context_value != context:
                return
        await super().close()
