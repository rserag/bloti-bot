"""Transport-neutral Bloti Bot command behavior."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from html import escape

from .gateway import BotActionError, BotGateway
from .groups import GroupError, GroupStore, group_name
from .jobs import Job, JobRegistry, StartResult
from .models import CommandContext, Member, ParsedCommand

logger = logging.getLogger(__name__)

ADMIN_ONLY = "Only chat administrators can use this command."
BOT_ADMIN_REQUIRED = "Please make me an administrator before using this command."
ALREADY_RUNNING = "A job is already running in this chat. Use /stop to cancel it."
AT_CAPACITY = "I am busy in other chats. Please try again shortly."
GENERIC_ERROR = "I could not complete that command. Please try again later."
GROUP_HELP = (
    "<b>Named groups in this chat</b>\n"
    "/group create NAME — create a group\n"
    "/group add NAME @user [@user …] — add current chat members\n"
    "/group remove NAME @user [@user …] — remove saved members\n"
    "Or reply to someone's message with /group add NAME or /group remove NAME.\n"
    "Numeric user IDs also work. Membership changes are admins only.\n"
    "/group show NAME — list saved members\n"
    "/group delete NAME — delete the saved group (admins only)\n"
    "/groups — list groups\n"
    "/NAME [message] — mention the group's current chat members\n"
    "/pinggroup NAME [message] — the same mention command"
)


class BotService:
    def __init__(
        self,
        gateway: BotGateway,
        *,
        source_url: str,
        version: str,
        max_active_chats: int = 4,
        message_delay_seconds: float = 1.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        groups: GroupStore | None = None,
    ) -> None:
        self.gateway = gateway
        self.source_url = source_url
        self.version = version
        self.message_delay_seconds = message_delay_seconds
        self.sleep = sleep
        self.jobs = JobRegistry(max_active_chats)
        self.groups = groups

    async def handle(self, context: CommandContext, command: ParsedCommand) -> None:
        handlers: dict[str, Callable[[CommandContext, str], Awaitable[None]]] = {
            "admins": self.admins,
            "bots": self.bots,
            "group": self.group,
            "groups": self.list_groups,
            "help": self.help,
            "ping": self.ping,
            "pinggroup": self.ping_group,
            "remove": self.remove,
            "source": self.source,
            "start": self.start,
            "stop": self.stop,
            "version": self.show_version,
        }
        handler = handlers.get(command.name)
        try:
            if handler is not None:
                await handler(context, command.argument)
            elif (
                self.groups is not None
                and not context.is_private
                and not context.is_channel_post
                and await self.groups.exists(context.chat_id, command.name)
            ):
                await self.ping_group(context, f"{command.name} {command.argument}".strip())
        except GroupError as exc:
            await self.gateway.send(context, escape(str(exc)))
        except BotActionError:
            logger.warning("Telegram rejected command action", extra={"command": command.name})
            await self.gateway.send(context, GENERIC_ERROR)
        except Exception:
            logger.exception("Unexpected command failure", extra={"command": command.name})
            await self.gateway.send(context, GENERIC_ERROR)

    async def _ensure_admin(self, context: CommandContext) -> bool:
        if context.is_channel_post or context.is_anonymous_admin:
            return True
        if context.sender_id is None:
            await self.gateway.send(context, ADMIN_ONLY)
            return False
        if not await self.gateway.is_chat_admin(context.chat_id, context.sender_id):
            await self.gateway.send(context, ADMIN_ONLY)
            return False
        return True

    async def _start_job(self, context: CommandContext) -> Job | None:
        result, job = await self.jobs.try_start(context.chat_id)
        if result is StartResult.ALREADY_RUNNING:
            await self.gateway.send(context, ALREADY_RUNNING)
        elif result is StartResult.AT_CAPACITY:
            await self.gateway.send(context, AT_CAPACITY)
        return job

    async def _wait_or_cancel(self, job: Job) -> bool:
        if job.cancelled.is_set():
            return True
        if self.message_delay_seconds <= 0:
            await self.sleep(0)
            return job.cancelled.is_set()
        try:
            await asyncio.wait_for(job.cancelled.wait(), timeout=self.message_delay_seconds)
        except TimeoutError:
            return False
        return True

    async def ping(self, context: CommandContext, argument: str) -> None:
        await self._mention(context, self.gateway.iter_members(context.chat_id), argument)

    async def _mention(
        self,
        context: CommandContext,
        members: AsyncIterator[Member],
        argument: str,
        *,
        notify_empty: bool = False,
    ) -> None:
        job = await self._start_job(context)
        if job is None:
            return

        sent = 0
        cancelled = False
        heading = f"<b>{escape(argument)}</b>\n" if argument else ""
        batch: list[str] = []
        try:
            async for member in members:
                if job.cancelled.is_set():
                    cancelled = True
                    break
                if member.is_bot or member.is_deleted:
                    continue
                batch.append(member.mention_html)
                if len(batch) < 10:
                    continue
                await self.gateway.send(context, heading + " ".join(batch))
                sent += len(batch)
                batch.clear()
                if await self._wait_or_cancel(job):
                    cancelled = True
                    break

            if batch and not cancelled and not job.cancelled.is_set():
                await self.gateway.send(context, heading + " ".join(batch))
                sent += len(batch)

            if cancelled or job.cancelled.is_set():
                await self.gateway.send(
                    context,
                    f"Mention job cancelled: {sent} members notified.",
                )
            elif not sent and notify_empty:
                await self.gateway.send(
                    context, "No active members of that group were found in this chat."
                )
        finally:
            await self.jobs.finish(context.chat_id, job)

    def _group_store(self, context: CommandContext) -> GroupStore:
        if context.is_private or context.is_channel_post:
            raise GroupError("Named groups can only be used in group chats.")
        if self.groups is None:
            raise GroupError("Named group storage is unavailable. Please contact the bot operator.")
        return self.groups

    async def list_groups(self, context: CommandContext, argument: str) -> None:
        del argument
        groups = await self._group_store(context).list_groups(context.chat_id)
        if not groups:
            await self.gateway.send(context, "No groups yet. An admin can use /group create NAME.")
            return
        await self._send_group_lines(
            context,
            "<b>Groups in this chat</b>\n",
            [f"<code>{escape(name)}</code> — {count} member(s)\n" for name, count in groups],
        )

    async def _send_group_lines(
        self, context: CommandContext, heading: str, lines: Sequence[str]
    ) -> None:
        text = heading
        for line in lines:
            # Telegram measures message length in UTF-16 units. Including markup
            # in this conservative bound also handles names outside the BMP.
            if len((text + line).encode("utf-16-le")) // 2 > 3500:
                await self.gateway.send(context, text)
                text = heading
            text += line
        await self.gateway.send(context, text)

    async def _show_group(
        self, context: CommandContext, name: str, members: Sequence[Member]
    ) -> None:
        heading = f"<b>{escape(name)}</b> — {len(members)} saved member(s)\n"
        # Listing saved members should not send mention notifications. Keep each
        # message below Telegram's limit, including HTML markup and long names.
        await self._send_group_lines(
            context,
            heading,
            [
                f"{escape((m.first_name or 'Member')[:64])} — <code>{m.user_id}</code>\n"
                for m in members
            ],
        )

    async def group(self, context: CommandContext, argument: str) -> None:
        store = self._group_store(context)
        parts = argument.split()
        if not parts or parts[0].lower() not in {"create", "add", "remove", "show", "delete"}:
            await self.gateway.send(context, GROUP_HELP)
            return
        action = parts[0].lower()
        if action != "show" and not await self._ensure_admin(context):
            return
        if len(parts) < 2 or (action in {"create", "show", "delete"} and len(parts) != 2):
            raise GroupError(f"Usage: /group {action} NAME")
        name = group_name(parts[1])
        if action == "create":
            await store.create(context.chat_id, name)
            await self.gateway.send(context, f"Created group <code>{escape(name)}</code>.")
            return
        saved = await store.members(context.chat_id, name)
        if action == "show":
            await self._show_group(context, name, saved)
            return
        if action == "delete":
            await store.delete(context.chat_id, name)
            await self.gateway.send(context, f"Deleted group <code>{escape(name)}</code>.")
            return

        targets = parts[2:]
        # A reply identifies one person when no explicit targets were supplied.
        if not targets and context.reply_sender_id is not None:
            targets = [str(context.reply_sender_id)]
        if not targets:
            raise GroupError(
                f"Reply to a member's message with /group {action} {name}, "
                "or provide @usernames or numeric user IDs."
            )
        if len(targets) > 50:
            raise GroupError("Change at most 50 members in one command.")
        for target in targets:
            if not re.fullmatch(r"@[A-Za-z0-9_]+|[0-9]{1,19}", target):
                raise GroupError("Identify members with @usernames, numeric user IDs, or a reply.")
        candidates = (
            saved
            if action == "remove"
            else [
                member
                async for member in self.gateway.iter_members(context.chat_id)
                if not member.is_bot and not member.is_deleted
            ]
        )
        by_id = {str(member.user_id): member for member in candidates}
        by_username = {
            f"@{member.username.casefold()}": member for member in candidates if member.username
        }
        selected: dict[int, Member] = {}
        for target in targets:
            member = (by_username if target.startswith("@") else by_id).get(target.casefold())
            if member is None:
                detail = (
                    "a saved member of this group"
                    if action == "remove"
                    else "an active human in this chat"
                )
                raise GroupError(f"{target} is not {detail}. No members were changed.")
            selected[member.user_id] = member
        if action == "add":
            changed = await store.add(context.chat_id, name, list(selected.values()))
            verb = "Added"
        else:
            changed = await store.remove(context.chat_id, name, list(selected))
            verb = "Removed"
        await self.gateway.send(
            context,
            f"{verb} {changed} member(s) {'to' if action == 'add' else 'from'} "
            f"<code>{escape(name)}</code>.",
        )

    async def ping_group(self, context: CommandContext, argument: str) -> None:
        store = self._group_store(context)
        parts = argument.split(maxsplit=1)
        if not parts:
            raise GroupError("Usage: /pinggroup NAME [message]")
        name = group_name(parts[0])
        heading = parts[1] if len(parts) > 1 else ""
        if len(heading) > 512:
            raise GroupError("Keep the mention message to 512 characters or fewer.")
        saved = await store.members(context.chat_id, name)
        if not saved:
            await self.gateway.send(
                context, "That group is empty. An admin can add members with /group add."
            )
            return
        ids = {member.user_id for member in saved}

        async def current_members() -> AsyncIterator[Member]:
            async for member in self.gateway.iter_members(context.chat_id):
                if member.user_id in ids:
                    # Always mention the saved ID, never a reassigned username.
                    yield Member(
                        member.user_id,
                        first_name=member.first_name,
                        is_bot=member.is_bot,
                        is_deleted=member.is_deleted,
                    )

        await self._mention(context, current_members(), heading, notify_empty=True)

    async def stop(self, context: CommandContext, argument: str) -> None:
        del argument
        if not await self._ensure_admin(context):
            return
        if await self.jobs.cancel(context.chat_id):
            await self.gateway.send(context, "Cancellation requested for this chat.")
        else:
            await self.gateway.send(context, "There is no active job in this chat.")

    async def admins(self, context: CommandContext, argument: str) -> None:
        del argument
        members = [member async for member in self.gateway.iter_admins(context.chat_id)]
        if not members:
            await self.gateway.send(context, "No visible administrators were found.")
            return
        lines = ["<b>Chat administrators</b>"]
        lines.extend(
            f"{member.mention_html} — {'owner' if member.is_owner else 'admin'}"
            for member in members
        )
        await self.gateway.send(context, "\n".join(lines))

    async def bots(self, context: CommandContext, argument: str) -> None:
        del argument
        members = [member async for member in self.gateway.iter_bots(context.chat_id)]
        if not members:
            await self.gateway.send(context, "No bots were found in this chat.")
            return
        await self.gateway.send(
            context,
            "<b>Bots in this chat</b>\n" + "\n".join(member.mention_html for member in members),
        )

    async def remove(self, context: CommandContext, argument: str) -> None:
        del argument
        if not await self._ensure_admin(context):
            return
        if not await self.gateway.is_bot_admin(context.chat_id):
            await self.gateway.send(context, BOT_ADMIN_REQUIRED)
            return
        job = await self._start_job(context)
        if job is None:
            return

        progress_message_id: int | None = None
        removed = 0
        failed = 0
        cancelled = False
        try:
            deleted_members = [
                member
                async for member in self.gateway.iter_members(context.chat_id)
                if member.is_deleted
            ]
            if not deleted_members:
                await self.gateway.send(context, "No deleted accounts were found.")
                return

            estimate = max(1, round(len(deleted_members) * self.message_delay_seconds / 60))
            progress_message_id = await self.gateway.send(
                context,
                f"Removing {len(deleted_members)} deleted accounts (about {estimate} minute(s)).",
            )
            for member in deleted_members:
                if job.cancelled.is_set():
                    cancelled = True
                    break
                try:
                    await self.gateway.remove_member(context.chat_id, member.user_id)
                    removed += 1
                except BotActionError:
                    failed += 1
                    logger.warning("Unable to remove one deleted account")
                if await self._wait_or_cancel(job):
                    cancelled = True
                    break

            status = "cancelled" if cancelled else "complete"
            await self.gateway.send(
                context,
                f"Cleanup {status}: {removed} removed, {failed} failed.",
            )
        finally:
            if progress_message_id is not None:
                try:
                    await self.gateway.delete_message(context.chat_id, progress_message_id)
                except BotActionError:
                    logger.warning("Unable to delete cleanup progress message")
            await self.jobs.finish(context.chat_id, job)

    async def start(self, context: CommandContext, argument: str) -> None:
        del argument
        if context.is_private:
            await self.gateway.send(
                context,
                "Add me to a group, grant the permissions needed for moderation, and use /help.",
            )

    async def help(self, context: CommandContext, argument: str) -> None:
        del argument
        await self.gateway.send(
            context,
            "<b>Bloti Bot commands</b>\n"
            "/ping [message], /all — mention non-bot members\n"
            "/pinggroup NAME [message] — mention a saved group's members\n"
            "/NAME [message] — shortcut for a saved group\n"
            "/groups — list this chat's saved groups\n"
            "/group — named group help (changes are admins only)\n"
            "/admins — list visible administrators\n"
            "/bots — list bots\n"
            "/remove — remove deleted accounts (admins only)\n"
            "/stop — cancel this chat's active job (admins only)\n"
            "/source — source code\n"
            "/version — running version",
        )

    async def source(self, context: CommandContext, argument: str) -> None:
        del argument
        await self.gateway.send(
            context, f'<a href="{escape(self.source_url, quote=True)}">Source code</a>'
        )

    async def show_version(self, context: CommandContext, argument: str) -> None:
        del argument
        await self.gateway.send(context, f"Bloti Bot {escape(self.version)}")
