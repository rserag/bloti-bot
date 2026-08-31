from pathlib import Path

import pytest

from blotibot.config import ConfigError, Settings
from blotibot.models import Member, ParsedCommand, parse_command


def test_settings_load_secrets_from_files_without_exposing_them(tmp_path: Path) -> None:
    api_id = tmp_path / "api_id"
    api_hash = tmp_path / "api_hash"
    bot_token = tmp_path / "bot_token"
    api_id.write_text("12345\n", encoding="utf-8")
    api_hash.write_text("secret-hash\n", encoding="utf-8")
    bot_token.write_text("secret-token\n", encoding="utf-8")

    settings = Settings.from_env(
        {
            "API_ID_FILE": str(api_id),
            "API_HASH_FILE": str(api_hash),
            "BOT_TOKEN_FILE": str(bot_token),
        }
    )

    assert settings.api_id == 12345
    assert settings.api_hash == "secret-hash"
    assert settings.bot_token == "secret-token"
    assert "secret-hash" not in repr(settings)
    assert "secret-token" not in repr(settings)


@pytest.mark.parametrize(
    ("environment", "message"),
    [
        ({}, "API_ID"),
        ({"API_ID": "nope", "API_HASH": "x", "BOT_TOKEN": "y"}, "integer"),
        (
            {
                "API_ID": "1",
                "API_HASH": "x",
                "BOT_TOKEN": "y",
                "MAX_ACTIVE_CHATS": "0",
            },
            "positive",
        ),
        (
            {
                "API_ID": "1",
                "API_HASH": "x",
                "BOT_TOKEN": "y",
                "HEARTBEAT_INTERVAL_SECONDS": "0",
            },
            "HEARTBEAT_INTERVAL_SECONDS",
        ),
    ],
)
def test_settings_reject_invalid_values(environment: dict[str, str], message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        Settings.from_env(environment)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("/ping hello everyone", ParsedCommand("ping", "hello everyone")),
        ("/ping hello\neveryone", ParsedCommand("ping", "hello\neveryone")),
        ("/all@BlotiBot hello world", ParsedCommand("ping", "hello world")),
        ("/clean", ParsedCommand("remove", "")),
        ("/cancel", ParsedCommand("stop", "")),
        ("/unknown", None),
        ("ordinary text", None),
        (None, None),
    ],
)
def test_parse_command(text: str | None, expected: ParsedCommand | None) -> None:
    assert parse_command(text) == expected


def test_member_mentions_are_html_safe() -> None:
    assert Member(1, username="a&b").mention_html == "@a&amp;b"
    assert Member(2, first_name="<Admin>").mention_html == (
        '<a href="tg://user?id=2">&lt;Admin&gt;</a>'
    )
