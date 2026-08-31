"""Bloti Bot process entry point."""

from __future__ import annotations

import asyncio
import logging

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
    await client.run_until_disconnected()


def main() -> None:
    configure_logging()
    try:
        asyncio.run(run())
    except ConfigError as exc:
        raise SystemExit(f"Configuration error: {exc}") from exc


if __name__ == "__main__":
    main()
