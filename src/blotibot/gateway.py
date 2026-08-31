"""Telegram boundary used by the core service and its tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from .models import CommandContext, Member


class BotActionError(RuntimeError):
    """A user-safe failure returned by Telegram."""


class BotGateway(Protocol):
    async def is_chat_admin(self, chat_id: int, user_id: int) -> bool: ...

    async def is_bot_admin(self, chat_id: int) -> bool: ...

    def iter_members(self, chat_id: int) -> AsyncIterator[Member]: ...

    def iter_admins(self, chat_id: int) -> AsyncIterator[Member]: ...

    def iter_bots(self, chat_id: int) -> AsyncIterator[Member]: ...

    async def send(self, context: CommandContext, text: str) -> int: ...

    async def delete_message(self, chat_id: int, message_id: int) -> None: ...

    async def remove_member(self, chat_id: int, user_id: int) -> None: ...
