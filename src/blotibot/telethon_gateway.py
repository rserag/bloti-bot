"""Telethon implementation of the Telegram boundary."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, TypeVar

from telethon import TelegramClient
from telethon.errors import FloodWaitError, RPCError
from telethon.tl.types import ChannelParticipantsAdmins, ChannelParticipantsBots, User

from .gateway import BotActionError
from .models import CommandContext, Member

T = TypeVar("T")


class TelethonGateway:
    def __init__(self, client: TelegramClient, bot_user_id: int) -> None:
        self.client = client
        self.bot_user_id = bot_user_id

    async def _call(self, operation: Callable[[], Awaitable[T]]) -> T:
        while True:
            try:
                return await operation()
            except FloodWaitError as exc:
                await asyncio.sleep(exc.seconds)
            except RPCError as exc:
                raise BotActionError("Telegram rejected the operation") from exc

    async def is_chat_admin(self, chat_id: int, user_id: int) -> bool:
        permissions = await self._call(lambda: self.client.get_permissions(chat_id, user_id))
        return bool(permissions.is_admin or permissions.is_creator)

    async def is_bot_admin(self, chat_id: int) -> bool:
        return await self.is_chat_admin(chat_id, self.bot_user_id)

    @staticmethod
    def _member(user: User) -> Member:
        participant = getattr(user, "participant", None)
        participant_name = type(participant).__name__
        return Member(
            user_id=user.id,
            first_name=user.first_name,
            username=user.username,
            is_bot=bool(user.bot),
            is_deleted=bool(user.deleted),
            is_admin=participant_name.endswith(("Admin", "Creator")),
            is_owner=participant_name.endswith("Creator"),
        )

    async def _participants(
        self, chat_id: int, participant_filter: Any = None
    ) -> AsyncIterator[Member]:
        seen: set[int] = set()
        while True:
            try:
                iterator = self.client.iter_participants(chat_id, filter=participant_filter)
                async for user in iterator:
                    if not isinstance(user, User) or user.id in seen:
                        continue
                    seen.add(user.id)
                    yield self._member(user)
                return
            except FloodWaitError as exc:
                await asyncio.sleep(exc.seconds)
            except RPCError as exc:
                raise BotActionError("Unable to list chat participants") from exc

    def iter_members(self, chat_id: int) -> AsyncIterator[Member]:
        return self._participants(chat_id)

    def iter_admins(self, chat_id: int) -> AsyncIterator[Member]:
        return self._participants(chat_id, ChannelParticipantsAdmins())

    def iter_bots(self, chat_id: int) -> AsyncIterator[Member]:
        return self._participants(chat_id, ChannelParticipantsBots())

    async def send(self, context: CommandContext, text: str) -> int:
        message = await self._call(
            lambda: self.client.send_message(
                context.chat_id, text, parse_mode="html", link_preview=False
            )
        )
        return int(message.id)

    async def delete_message(self, chat_id: int, message_id: int) -> None:
        await self._call(lambda: self.client.delete_messages(chat_id, [message_id]))

    async def remove_member(self, chat_id: int, user_id: int) -> None:
        await self._call(lambda: self.client.kick_participant(chat_id, user_id))
