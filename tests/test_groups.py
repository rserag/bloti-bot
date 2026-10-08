import asyncio
from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path

import pytest
from test_service import FakeGateway, context

from blotibot.groups import MAX_GROUPS, MAX_MEMBERS, GroupError, GroupStore, group_name
from blotibot.models import ALIASES, KNOWN_COMMANDS, Member, ParsedCommand, parse_command
from blotibot.service import ADMIN_ONLY, ALREADY_RUNNING, AT_CAPACITY, BotService


@pytest.fixture
async def store(tmp_path: Path) -> GroupStore:
    groups = GroupStore(tmp_path / "state" / "groups.sqlite3")
    await groups.initialize()
    return groups


def service(gateway: FakeGateway, store: GroupStore) -> BotService:
    return BotService(
        gateway,
        source_url="https://github.com/rserag/bloti-bot",
        version="test",
        message_delay_seconds=0,
        groups=store,
    )


async def test_persistence_isolation_deduplication_and_delete_cascade(store: GroupStore) -> None:
    await store.create(100, "Bloti")
    await store.create(200, "bloti")
    member = Member(1, first_name="Alice", username="alice")
    assert await store.add(100, "BLOTI", [member, member]) == 1
    assert await store.add(100, "bloti", [member]) == 0
    reopened = GroupStore(store.path)
    await reopened.initialize()
    assert await reopened.members(100, "bloti") == [member]
    assert await reopened.members(200, "bloti") == []
    assert await reopened.list_groups(100) == [("bloti", 1)]
    assert store.path.stat().st_mode & 0o777 == 0o600
    await reopened.delete(100, "bloti")
    await reopened.create(100, "bloti")
    assert await reopened.members(100, "bloti") == []
    assert await reopened.list_groups(200) == [("bloti", 0)]


async def test_concurrent_creates_and_adds_do_not_lose_members(store: GroupStore) -> None:
    results = await asyncio.gather(
        store.create(100, "team"), store.create(100, "TEAM"), return_exceptions=True
    )
    assert sum(isinstance(result, GroupError) for result in results) == 1
    await asyncio.gather(*(store.add(100, "team", [Member(i)]) for i in range(1, 21)))
    assert len(await store.members(100, "team")) == 20


async def test_limits_are_atomic_and_missing_groups_are_not_created(store: GroupStore) -> None:
    with pytest.raises(GroupError, match="does not exist"):
        await store.add(100, "missing", [Member(1)])
    for i in range(MAX_GROUPS):
        await store.create(100, f"group{i}")
    with pytest.raises(GroupError, match="maximum"):
        await store.create(100, "overflow")
    original = [Member(i) for i in range(1, MAX_MEMBERS + 1)]
    await store.add(100, "group0", original)
    with pytest.raises(GroupError, match="at most"):
        await store.add(100, "group0", [Member(1, first_name="Changed"), Member(MAX_MEMBERS + 1)])
    assert await store.members(100, "group0") == original


@pytest.mark.parametrize("name", ["", "a b", "../x", "<b>", "a" * 33])
def test_invalid_group_names(name: str) -> None:
    with pytest.raises(GroupError):
        group_name(name)


def test_unicode_group_names_and_command_parsing() -> None:
    assert group_name("ԲԼՈՏ") == "բլոտ"
    assert parse_command("/group@BlotiBot add team @alice") == ParsedCommand(
        "group", "add team @alice"
    )
    assert parse_command("/groups") == ParsedCommand("groups")
    assert parse_command("/pinggroup TEAM hello everyone") == ParsedCommand(
        "pinggroup", "TEAM hello everyone"
    )


@pytest.mark.parametrize(
    "argument", ["create team", "add team @alice", "remove team @alice", "delete team"]
)
async def test_mutations_require_admin(store: GroupStore, argument: str) -> None:
    gateway = FakeGateway()
    await store.create(100, "team")
    await service(gateway, store).handle(context(), ParsedCommand("group", argument))
    assert gateway.sent[-1][1] == ADMIN_ONLY
    assert await store.members(100, "team") == []


async def test_create_add_reply_and_remove_saved_member_after_leaving(store: GroupStore) -> None:
    gateway = FakeGateway()
    gateway.admins.add((100, 7))
    gateway.members = [Member(1, first_name="Alice", username="alice"), Member(2, first_name="Bob")]
    bot = service(gateway, store)
    await bot.handle(context(), ParsedCommand("group", "create team"))
    await bot.handle(context(), ParsedCommand("group", "add TEAM @ALICE @alice"))
    await bot.handle(replace(context(), reply_sender_id=2), ParsedCommand("group", "add team"))
    assert gateway.sent[-2][1] == "Added 1 member(s) to <code>team</code>."
    assert len(await store.members(100, "team")) == 2
    gateway.members = []
    await bot.handle(context(), ParsedCommand("group", "remove team @alice"))
    await bot.handle(replace(context(), reply_sender_id=2), ParsedCommand("group", "remove team"))
    assert await store.members(100, "team") == []
    assert gateway.removed_members == []


async def test_explicit_targets_take_precedence_over_reply(store: GroupStore) -> None:
    await store.create(100, "team")
    gateway = FakeGateway()
    gateway.admins.add((100, 7))
    gateway.members = [Member(1, username="alice"), Member(2)]
    await service(gateway, store).handle(
        replace(context(), reply_sender_id=2), ParsedCommand("group", "add team @alice")
    )
    assert [m.user_id for m in await store.members(100, "team")] == [1]


@pytest.mark.parametrize("invalid", ["@missing", "2", "3", "<bad>", "-100"])
async def test_add_validates_entire_batch_before_saving(store: GroupStore, invalid: str) -> None:
    await store.create(100, "team")
    gateway = FakeGateway()
    gateway.admins.add((100, 7))
    gateway.members = [
        Member(1, username="alice"),
        Member(2, is_bot=True),
        Member(3, is_deleted=True),
    ]
    await service(gateway, store).handle(
        context(), ParsedCommand("group", f"add team @alice {invalid}")
    )
    assert await store.members(100, "team") == []
    assert len(gateway.sent) == 1
    assert "<bad>" not in gateway.sent[0][1]


async def test_remove_validates_entire_batch_before_saving(store: GroupStore) -> None:
    await store.create(100, "team")
    await store.add(100, "team", [Member(1, username="alice")])
    gateway = FakeGateway()
    gateway.admins.add((100, 7))
    await service(gateway, store).handle(context(), ParsedCommand("group", "remove team 1 2"))
    assert len(await store.members(100, "team")) == 1
    assert "No members were changed" in gateway.sent[0][1]


async def test_group_mentions_use_ids_and_filter_current_members(store: GroupStore) -> None:
    await store.create(100, "team")
    await store.add(100, "team", [Member(i, username=f"old{i}") for i in range(1, 6)])
    gateway = FakeGateway()
    gateway.members = [
        Member(1, first_name="<Alice>", username="newname"),
        Member(2, first_name="Bot", is_bot=True),
        Member(3, is_deleted=True),
        Member(99, username="old1"),
    ]
    await service(gateway, store).handle(context(), ParsedCommand("pinggroup", "TEAM Play <now>!"))
    assert [text for _, text, _ in gateway.sent] == [
        '<b>Play &lt;now&gt;!</b>\n<a href="tg://user?id=1">&lt;Alice&gt;</a>'
    ]


async def test_group_mentions_batch_and_cancel_with_existing_stop(store: GroupStore) -> None:
    await store.create(100, "team")
    gateway = FakeGateway()
    gateway.members = [Member(i, first_name=f"User {i}") for i in range(1, 24)]
    gateway.admins.add((100, 7))
    await store.add(100, "team", gateway.members)
    bot = service(gateway, store)
    await bot.handle(context(), ParsedCommand("pinggroup", "team Hello"))
    assert len(gateway.sent) == 3
    assert all(text.startswith("<b>Hello</b>") for _, text, _ in gateway.sent)
    gateway.sent.clear()

    async def stop(_: float) -> None:
        await bot.stop(context(), "")

    bot.sleep = stop
    await bot.handle(context(), ParsedCommand("pinggroup", "team"))
    assert gateway.sent[-1][1] == "Mention job cancelled: 10 members notified."
    assert not await bot.jobs.is_running(100)


async def test_group_mentions_share_job_limits_and_release_on_failure(store: GroupStore) -> None:
    await store.create(100, "team")
    await store.add(100, "team", [Member(1)])
    gateway = FakeGateway()
    gateway.members = [Member(1)]
    bot = service(gateway, store)
    _, job = await bot.jobs.try_start(100)
    assert job is not None
    await bot.ping_group(context(), "team")
    assert gateway.sent[-1][1] == ALREADY_RUNNING
    await bot.jobs.finish(100, job)
    for chat_id in range(200, 204):
        await bot.jobs.try_start(chat_id)
    await bot.ping_group(context(), "team")
    assert gateway.sent[-1][1] == AT_CAPACITY
    bot = service(gateway, store)
    gateway.fail_send_number = len(gateway.sent) + 1
    with pytest.raises(RuntimeError, match="simulated"):
        await bot.ping_group(context(), "team")
    assert not await bot.jobs.is_running(100)


async def test_cancellation_during_member_lookup_does_not_send_buffered_mentions(
    store: GroupStore,
) -> None:
    await store.create(100, "team")
    await store.add(100, "team", [Member(1)])
    bot: BotService

    class CancellingGateway(FakeGateway):
        async def _iterate(self, values: list[Member]) -> AsyncIterator[Member]:
            for value in values:
                yield value
            await bot.jobs.cancel(100)

    gateway = CancellingGateway()
    gateway.members = [Member(1)]
    bot = service(gateway, store)
    await bot.handle(context(), ParsedCommand("pinggroup", "team"))
    assert [text for _, text, _ in gateway.sent] == ["Mention job cancelled: 0 members notified."]
    assert not await bot.jobs.is_running(100)


async def test_missing_empty_and_departed_groups_give_feedback(store: GroupStore) -> None:
    gateway = FakeGateway()
    bot = service(gateway, store)
    await bot.handle(context(), ParsedCommand("pinggroup", "missing"))
    assert "does not exist" in gateway.sent[-1][1]
    await store.create(100, "team")
    await bot.handle(context(), ParsedCommand("pinggroup", "team"))
    assert "empty" in gateway.sent[-1][1]
    await store.add(100, "team", [Member(1)])
    await bot.handle(context(), ParsedCommand("pinggroup", "team"))
    assert "No active members" in gateway.sent[-1][1]
    await bot.handle(context(200), ParsedCommand("pinggroup", "team"))
    assert "does not exist" in gateway.sent[-1][1]


@pytest.mark.parametrize("command", ["group", "groups", "pinggroup"])
@pytest.mark.parametrize("flags", [{"is_private": True}, {"is_channel_post": True}])
async def test_group_commands_reject_non_group_chats(
    store: GroupStore, command: str, flags: dict[str, bool]
) -> None:
    gateway = FakeGateway()
    ctx = replace(
        context(),
        is_private=flags.get("is_private", False),
        is_channel_post=flags.get("is_channel_post", False),
    )
    await service(gateway, store).handle(ctx, ParsedCommand(command, "team"))
    assert "only be used in group chats" in gateway.sent[-1][1]


async def test_list_and_show_do_not_notify_and_split_large_rosters(store: GroupStore) -> None:
    await store.create(100, "team")
    await store.add(100, "team", [Member(i, first_name="<Alice>" * 9) for i in range(1, 501)])
    gateway = FakeGateway()
    bot = service(gateway, store)
    await bot.handle(context(), ParsedCommand("groups"))
    assert "team</code> — 500 member(s)" in gateway.sent[-1][1]
    gateway.sent.clear()
    await bot.handle(context(), ParsedCommand("group", "show team"))
    assert len(gateway.sent) > 1
    assert all(len(text) <= 3500 and "tg://" not in text for _, text, _ in gateway.sent)
    assert "&lt;Alice&gt;" in gateway.sent[0][1]
    assert "<code>500</code>" in gateway.sent[-1][1]


async def test_group_help_and_long_heading_validation(store: GroupStore) -> None:
    gateway = FakeGateway()
    bot = service(gateway, store)
    await bot.handle(context(), ParsedCommand("group"))
    assert "/group add NAME" in gateway.sent[-1][1]
    await bot.handle(context(), ParsedCommand("help"))
    assert "/pinggroup NAME" in gateway.sent[-1][1]
    await bot.handle(context(), ParsedCommand("pinggroup", "team " + "x" * 513))
    assert "512 characters" in gateway.sent[-1][1]


async def test_rosters_and_group_lists_handle_non_bmp_names(store: GroupStore) -> None:
    for i in range(MAX_GROUPS):
        await store.create(100, "𐐀" * 30 + str(i))
    name = "𐐀" * 30 + "0"
    await store.add(100, name, [Member(i, first_name="𐐀" * 64) for i in range(1, 101)])
    gateway = FakeGateway()
    bot = service(gateway, store)
    await bot.handle(context(), ParsedCommand("groups"))
    await bot.handle(context(), ParsedCommand("group", f"show {name}"))
    assert all(len(text.encode("utf-16-le")) // 2 <= 3500 for _, text, _ in gateway.sent)


@pytest.mark.parametrize("text", ["/bloti", "/BLOTI", "/bloti@BlotiBot"])
async def test_group_name_shortcut_mentions_saved_members(store: GroupStore, text: str) -> None:
    await store.create(100, "bloti")
    await store.add(100, "bloti", [Member(1)])
    gateway = FakeGateway()
    gateway.members = [Member(1, first_name="Alice"), Member(2, first_name="Other")]
    command = parse_command(text)
    assert command is not None
    await service(gateway, store).handle(context(), command)
    assert [text for _, text, _ in gateway.sent] == ['<a href="tg://user?id=1">Alice</a>']


async def test_group_shortcut_preserves_optional_heading_and_job_limit(store: GroupStore) -> None:
    await store.create(100, "bloti")
    await store.add(100, "bloti", [Member(1)])
    gateway = FakeGateway()
    gateway.members = [Member(1, first_name="Alice")]
    bot = service(gateway, store)
    command = parse_command("/bloti Time to <play>!\nBring cards")
    assert command is not None
    await bot.handle(context(), command)
    assert gateway.sent[-1][1] == (
        '<b>Time to &lt;play&gt;!\nBring cards</b>\n<a href="tg://user?id=1">Alice</a>'
    )
    await bot.jobs.try_start(100)
    await bot.handle(context(), command)
    assert gateway.sent[-1][1] == ALREADY_RUNNING


async def test_shortcuts_are_chat_scoped_and_unknown_or_deleted_groups_are_ignored(
    store: GroupStore,
) -> None:
    await store.create(100, "bloti")
    gateway = FakeGateway()
    bot = service(gateway, store)
    await bot.handle(context(200), ParsedCommand("bloti"))
    await bot.handle(context(), ParsedCommand("unknown"))
    await bot.handle(replace(context(), is_private=True), ParsedCommand("bloti"))
    await bot.handle(replace(context(), is_channel_post=True), ParsedCommand("bloti"))
    assert gateway.sent == []
    await bot.handle(context(), ParsedCommand("bloti"))
    assert "empty" in gateway.sent[-1][1]
    gateway.sent.clear()
    await store.delete(100, "bloti")
    await bot.handle(context(), ParsedCommand("bloti"))
    assert gateway.sent == []


@pytest.mark.parametrize("name", sorted(KNOWN_COMMANDS | ALIASES.keys()))
async def test_group_names_cannot_override_builtin_commands_or_aliases(
    store: GroupStore,
    name: str,
) -> None:
    with pytest.raises(GroupError, match="reserved"):
        await store.create(100, name.upper())
    assert await store.list_groups(100) == []


async def test_builtin_commands_keep_their_behavior_with_group_shortcuts(store: GroupStore) -> None:
    await store.create(100, "bloti")
    gateway = FakeGateway()
    gateway.members = [Member(1), Member(2)]
    bot = service(gateway, store)
    command = parse_command("/all")
    assert command is not None
    await bot.handle(context(), command)
    assert "tg://user?id=1" in gateway.sent[-1][1]
    assert "tg://user?id=2" in gateway.sent[-1][1]
    await bot.handle(context(), ParsedCommand("help"))
    assert "/NAME [message]" in gateway.sent[-1][1]
