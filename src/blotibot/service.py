"""Transport-neutral Bloti Bot command behavior."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from html import escape

from .gateway import BotActionError, BotGateway
from .jobs import Job, JobRegistry, StartResult
from .models import CommandContext, ParsedCommand

logger = logging.getLogger(__name__)

ADMIN_ONLY = "Only chat administrators can use this command."
BOT_ADMIN_REQUIRED = "Please make me an administrator before using this command."
ALREADY_RUNNING = "A job is already running in this chat. Use /stop to cancel it."
AT_CAPACITY = "I am busy in other chats. Please try again shortly."
GENERIC_ERROR = "I could not complete that command. Please try again later."


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
    ) -> None:
        self.gateway = gateway
        self.source_url = source_url
        self.version = version
        self.message_delay_seconds = message_delay_seconds
        self.sleep = sleep
        self.jobs = JobRegistry(max_active_chats)

    async def handle(self, context: CommandContext, command: ParsedCommand) -> None:
        handlers: dict[str, Callable[[CommandContext, str], Awaitable[None]]] = {
            "admins": self.admins,
            "bots": self.bots,
            "help": self.help,
            "ping": self.ping,
            "remove": self.remove,
            "source": self.source,
            "start": self.start,
            "stop": self.stop,
            "version": self.show_version,
        }
        handler = handlers.get(command.name)
        if handler is None:
            return
        try:
            await handler(context, command.argument)
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
        if not await self._ensure_admin(context):
            return
        job = await self._start_job(context)
        if job is None:
            return

        sent = 0
        cancelled = False
        heading = f"<b>{escape(argument)}</b>\n" if argument else ""
        batch: list[str] = []
        try:
            async for member in self.gateway.iter_members(context.chat_id):
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

            if batch and not cancelled:
                await self.gateway.send(context, heading + " ".join(batch))
                sent += len(batch)

            status = "cancelled" if cancelled or job.cancelled.is_set() else "complete"
            await self.gateway.send(context, f"Mention job {status}: {sent} members notified.")
        finally:
            await self.jobs.finish(context.chat_id, job)

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
            "/ping [message] — mention non-bot members (admins only)\n"
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
