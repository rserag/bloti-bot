"""Map incoming Telethon messages to core commands."""

from __future__ import annotations

from typing import Any

from telethon import TelegramClient, events
from telethon.tl.types import Channel

from .models import CommandContext, parse_command
from .service import BotService


def register_handlers(
    client: TelegramClient, service: BotService, *, bot_username: str | None = None
) -> None:
    @client.on(events.NewMessage(incoming=True))  # type: ignore[untyped-decorator]
    async def command_handler(event: Any) -> None:
        command = parse_command(event.raw_text, bot_username=bot_username)
        if command is None:
            return
        chat = await event.get_chat()
        title = getattr(chat, "title", None) or getattr(chat, "first_name", None) or "Private chat"
        reply_sender_id = None
        if command.name == "group" and command.argument.lower().split(maxsplit=1)[0:1] in (
            ["add"],
            ["remove"],
        ):
            reply = await event.get_reply_message()
            if reply is not None and reply.chat_id == event.chat_id:
                reply_sender_id = reply.sender_id
        context = CommandContext(
            chat_id=event.chat_id,
            sender_id=event.sender_id,
            message_id=event.id,
            chat_title=title,
            is_private=event.is_private,
            is_channel_post=isinstance(chat, Channel)
            and bool(getattr(event.message, "post", False)),
            is_anonymous_admin=event.sender_id == event.chat_id and not event.is_private,
            reply_sender_id=reply_sender_id,
        )
        await service.handle(context, command)
