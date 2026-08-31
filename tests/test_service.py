from collections.abc import AsyncIterator

import pytest

from blotibot.gateway import BotActionError
from blotibot.models import CommandContext, Member
from blotibot.service import ADMIN_ONLY, BotService


class FakeGateway:
    def __init__(self) -> None:
        self.members: list[Member] = []
        self.admin_members: list[Member] = []
        self.bot_members: list[Member] = []
        self.admins: set[tuple[int, int]] = set()
        self.bot_admin_chats: set[int] = set()
        self.sent: list[tuple[int, str, int]] = []
        self.deleted_messages: list[tuple[int, int]] = []
        self.removed_members: list[tuple[int, int]] = []
        self.remove_failures: set[int] = set()
        self.fail_send_number: int | None = None

    async def is_chat_admin(self, chat_id: int, user_id: int) -> bool:
        return (chat_id, user_id) in self.admins

    async def is_bot_admin(self, chat_id: int) -> bool:
        return chat_id in self.bot_admin_chats

    async def _iterate(self, values: list[Member]) -> AsyncIterator[Member]:
        for value in values:
            yield value

    def iter_members(self, chat_id: int) -> AsyncIterator[Member]:
        del chat_id
        return self._iterate(self.members)

    def iter_admins(self, chat_id: int) -> AsyncIterator[Member]:
        del chat_id
        return self._iterate(self.admin_members)

    def iter_bots(self, chat_id: int) -> AsyncIterator[Member]:
        del chat_id
        return self._iterate(self.bot_members)

    async def send(self, context: CommandContext, text: str) -> int:
        message_id = len(self.sent) + 1
        if self.fail_send_number == message_id:
            raise RuntimeError("simulated send failure")
        self.sent.append((context.chat_id, text, message_id))
        return message_id

    async def delete_message(self, chat_id: int, message_id: int) -> None:
        self.deleted_messages.append((chat_id, message_id))

    async def remove_member(self, chat_id: int, user_id: int) -> None:
        if user_id in self.remove_failures:
            raise BotActionError("simulated Telegram rejection")
        self.removed_members.append((chat_id, user_id))


def context(chat_id: int = 100, sender_id: int = 7) -> CommandContext:
    return CommandContext(
        chat_id=chat_id,
        sender_id=sender_id,
        message_id=1,
        chat_title="Test group",
    )


def service(gateway: FakeGateway) -> BotService:
    return BotService(
        gateway,
        source_url="https://github.com/rserag/bloti-bot",
        version="test",
        message_delay_seconds=0,
    )


async def test_ping_requires_admin() -> None:
    gateway = FakeGateway()
    await service(gateway).ping(context(), "hello")
    assert [message for _, message, _ in gateway.sent] == [ADMIN_ONLY]


async def test_ping_accepts_verified_anonymous_admin_context() -> None:
    gateway = FakeGateway()
    gateway.members = [Member(1, first_name="Member")]
    anonymous_context = CommandContext(
        chat_id=100,
        sender_id=100,
        message_id=1,
        chat_title="Test group",
        is_anonymous_admin=True,
    )

    await service(gateway).ping(anonymous_context, "")

    assert gateway.sent[-1][1] == "Mention job complete: 1 members notified."


async def test_ping_filters_and_batches_members_and_preserves_full_argument() -> None:
    gateway = FakeGateway()
    gateway.admins.add((100, 7))
    gateway.members = [Member(i, first_name=f"User {i}") for i in range(1, 24)]
    gateway.members.extend([Member(24, first_name="Bot", is_bot=True), Member(25, is_deleted=True)])

    await service(gateway).ping(context(), "hello <everyone> today")

    messages = [message for _, message, _ in gateway.sent]
    assert len(messages) == 4
    assert all("<b>hello &lt;everyone&gt; today</b>" in message for message in messages[:3])
    assert messages[-1] == "Mention job complete: 23 members notified."
    assert "Bot" not in "".join(messages)


async def test_ping_releases_job_after_unexpected_failure() -> None:
    gateway = FakeGateway()
    gateway.admins.add((100, 7))
    gateway.members = [Member(i, first_name=f"User {i}") for i in range(1, 12)]
    gateway.fail_send_number = 1
    bot = service(gateway)

    with pytest.raises(RuntimeError, match="simulated"):
        await bot.ping(context(), "")

    assert not await bot.jobs.is_running(100)


async def test_remove_deleted_accounts_reports_failures_and_cleans_progress() -> None:
    gateway = FakeGateway()
    gateway.admins.add((100, 7))
    gateway.bot_admin_chats.add(100)
    gateway.members = [
        Member(1, is_deleted=True),
        Member(2, first_name="Active"),
        Member(3, is_deleted=True),
    ]
    gateway.remove_failures.add(3)

    await service(gateway).remove(context(), "")

    assert gateway.removed_members == [(100, 1)]
    assert gateway.deleted_messages == [(100, 1)]
    assert gateway.sent[-1][1] == "Cleanup complete: 1 removed, 1 failed."


async def test_empty_admin_and_bot_lists_are_handled() -> None:
    gateway = FakeGateway()
    bot = service(gateway)

    await bot.admins(context(), "")
    await bot.bots(context(), "")

    assert [message for _, message, _ in gateway.sent] == [
        "No visible administrators were found.",
        "No bots were found in this chat.",
    ]
