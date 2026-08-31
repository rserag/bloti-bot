"""Runtime configuration with support for file-mounted secrets."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path


class ConfigError(ValueError):
    """Raised when required configuration is missing or invalid."""


def _secret(
    environment: Mapping[str, str],
    name: str,
    *,
    required: bool = True,
) -> str:
    file_name = environment.get(f"{name}_FILE", "").strip()
    if file_name:
        try:
            value = Path(file_name).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ConfigError(f"Unable to read {name}_FILE") from exc
    else:
        value = environment.get(name, "").strip()

    if required and not value:
        raise ConfigError(f"Missing required setting: {name} or {name}_FILE")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    api_id: int
    api_hash: str = field(repr=False)
    bot_token: str = field(repr=False)
    session_path: Path = Path("/var/lib/blotibot/blotibot")
    source_url: str = "https://github.com/rserag/bloti-bot"
    version: str = "0.1.0"
    max_active_chats: int = 4
    message_delay_seconds: float = 1.0

    @classmethod
    def from_env(cls, environment: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if environment is None else environment
        raw_api_id = _secret(env, "API_ID")
        try:
            api_id = int(raw_api_id)
        except ValueError as exc:
            raise ConfigError("API_ID must be an integer") from exc

        try:
            max_active_chats = int(env.get("MAX_ACTIVE_CHATS", "4"))
            message_delay_seconds = float(env.get("MESSAGE_DELAY_SECONDS", "1"))
        except ValueError as exc:
            raise ConfigError("Concurrency and delay settings must be numeric") from exc

        if api_id <= 0:
            raise ConfigError("API_ID must be positive")
        if max_active_chats <= 0:
            raise ConfigError("MAX_ACTIVE_CHATS must be positive")
        if message_delay_seconds < 0:
            raise ConfigError("MESSAGE_DELAY_SECONDS cannot be negative")

        return cls(
            api_id=api_id,
            api_hash=_secret(env, "API_HASH"),
            bot_token=_secret(env, "BOT_TOKEN"),
            session_path=Path(env.get("SESSION_PATH", "/var/lib/blotibot/blotibot")),
            source_url=env.get("SOURCE_URL", "https://github.com/rserag/bloti-bot"),
            version=env.get("APP_VERSION", "0.1.0"),
            max_active_chats=max_active_chats,
            message_delay_seconds=message_delay_seconds,
        )
