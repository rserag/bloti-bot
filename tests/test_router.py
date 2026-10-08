from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any, cast

import pytest
from telethon import TelegramClient

from blotibot.models import CommandContext, ParsedCommand
from blotibot.router import register_handlers
from blotibot.service import BotService


class RecordingService:
    def __init__(self) -> None:
        self.calls: list[tuple[CommandContext, ParsedCommand]] = []

    async def handle(self, context: CommandContext, command: ParsedCommand) -> None:
        self.calls.append((context, command))


class RecordingClient:
    def __init__(self) -> None:
        self.handler: Callable[[Any], Awaitable[None]] | None = None

    def on(
        self, event: object
    ) -> Callable[[Callable[[Any], Awaitable[None]]], Callable[[Any], Awaitable[None]]]:
        def register(handler: Callable[[Any], Awaitable[None]]) -> Callable[[Any], Awaitable[None]]:
            self.handler = handler
            return handler

        return register


class FakeEvent:
    def __init__(self, text: str, reply: SimpleNamespace | None = None) -> None:
        self.raw_text = text
        self.chat_id = -100123
        self.sender_id = 7
        self.id = 10
        self.is_private = False
        self.reply = reply
        self.reply_reads = 0

    async def get_chat(self) -> SimpleNamespace:
        return SimpleNamespace(title="Test group")

    async def get_reply_message(self) -> SimpleNamespace | None:
        self.reply_reads += 1
        return self.reply


@pytest.mark.parametrize("action", ["add", "remove", "ADD"])
async def test_router_identifies_replied_to_member(action: str) -> None:
    client = RecordingClient()
    service = RecordingService()
    register_handlers(cast(TelegramClient, client), cast(BotService, service))
    assert client.handler is not None
    event = FakeEvent(
        f"/group@BlotiBot {action} team", SimpleNamespace(chat_id=-100123, sender_id=42)
    )
    await client.handler(event)
    context, command = service.calls[0]
    assert context.reply_sender_id == 42
    assert context.chat_id == -100123
    assert command == ParsedCommand("group", f"{action} team")


async def test_router_ignores_reply_from_another_chat_and_missing_reply() -> None:
    client = RecordingClient()
    service = RecordingService()
    register_handlers(cast(TelegramClient, client), cast(BotService, service))
    assert client.handler is not None
    for reply in [None, SimpleNamespace(chat_id=-100999, sender_id=42)]:
        await client.handler(FakeEvent("/group add team", reply))
        assert service.calls[-1][0].reply_sender_id is None


async def test_router_does_not_fetch_replies_for_other_commands() -> None:
    client = RecordingClient()
    service = RecordingService()
    register_handlers(cast(TelegramClient, client), cast(BotService, service))
    assert client.handler is not None
    event = FakeEvent("/pinggroup team")
    await client.handler(event)
    assert event.reply_reads == 0
    assert service.calls[0][1].name == "pinggroup"


async def test_router_passes_group_shortcuts_and_ignores_commands_for_other_bots() -> None:
    client = RecordingClient()
    service = RecordingService()
    register_handlers(
        cast(TelegramClient, client), cast(BotService, service), bot_username="BlotiBot"
    )
    assert client.handler is not None
    await client.handler(FakeEvent("/bloti@OtherBot"))
    assert service.calls == []
    event = FakeEvent("/BLOTI@bLoTiBoT Time to play!")
    await client.handler(event)
    assert service.calls[0][1] == ParsedCommand("bloti", "Time to play!")
    assert event.reply_reads == 0
