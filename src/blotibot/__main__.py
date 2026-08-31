"""Bloti Bot process entry point."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from pathlib import Path

from telethon import TelegramClient

from .config import ConfigError, Settings
from .router import register_handlers
from .service import BotService
from .telethon_gateway import TelethonGateway


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger("telethon").setLevel(logging.WARNING)


async def maintain_heartbeat(
    client: TelegramClient,
    path: Path,
    interval_seconds: float,
) -> None:
    await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
    while True:
        if client.is_connected():
            await asyncio.to_thread(path.touch)
        else:
            await asyncio.to_thread(path.unlink, missing_ok=True)
        await asyncio.sleep(interval_seconds)


async def run() -> None:
    settings = Settings.from_env()
    settings.session_path.parent.mkdir(parents=True, exist_ok=True)
    client = TelegramClient(str(settings.session_path), settings.api_id, settings.api_hash)
    await client.start(bot_token=settings.bot_token)
    identity = await client.get_me()
    if identity is None or not identity.bot:
        await client.disconnect()
        raise RuntimeError("Configured credentials do not belong to a bot")

    gateway = TelethonGateway(client, identity.id)
    service = BotService(
        gateway,
        source_url=settings.source_url,
        version=settings.version,
        max_active_chats=settings.max_active_chats,
        message_delay_seconds=settings.message_delay_seconds,
    )
    register_handlers(client, service)
    logging.getLogger(__name__).info("Bloti Bot started")
    heartbeat = asyncio.create_task(
        maintain_heartbeat(
            client,
            settings.heartbeat_path,
            settings.heartbeat_interval_seconds,
        )
    )
    try:
        await client.run_until_disconnected()
    finally:
        heartbeat.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat
        await asyncio.to_thread(settings.heartbeat_path.unlink, missing_ok=True)
        if client.is_connected():
            await client.disconnect()


def main() -> None:
    configure_logging()
    try:
        asyncio.run(run())
    except ConfigError as exc:
        raise SystemExit(f"Configuration error: {exc}") from exc


if __name__ == "__main__":
    main()
