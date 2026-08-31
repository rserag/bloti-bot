"""Transport-neutral command and member models."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape


@dataclass(frozen=True, slots=True)
class Member:
    user_id: int
    first_name: str | None = None
    username: str | None = None
    is_bot: bool = False
    is_deleted: bool = False
    is_admin: bool = False
    is_owner: bool = False

    @property
    def mention_html(self) -> str:
        if self.username:
            return f"@{escape(self.username)}"
        display_name = escape(self.first_name or "Member")
        return f'<a href="tg://user?id={self.user_id}">{display_name}</a>'


@dataclass(frozen=True, slots=True)
class CommandContext:
    chat_id: int
    sender_id: int | None
    message_id: int
    chat_title: str
    is_private: bool = False
    is_channel_post: bool = False
    is_anonymous_admin: bool = False


@dataclass(frozen=True, slots=True)
class ParsedCommand:
    name: str
    argument: str = ""


ALIASES = {
    "all": "ping",
    "cancel": "stop",
    "clean": "remove",
    "staff": "admins",
}

KNOWN_COMMANDS = {
    "admins",
    "bots",
    "help",
    "ping",
    "remove",
    "source",
    "start",
    "stop",
    "version",
}


def parse_command(text: str | None) -> ParsedCommand | None:
    if not text:
        return None
    stripped = text.strip()
    if not stripped.startswith("/"):
        return None
    command_parts = stripped.split(maxsplit=1)
    command_token = command_parts[0]
    argument = command_parts[1].strip() if len(command_parts) == 2 else ""
    name = command_token[1:].split("@", maxsplit=1)[0].lower()
    name = ALIASES.get(name, name)
    if name not in KNOWN_COMMANDS:
        return None
    return ParsedCommand(name=name, argument=argument)
