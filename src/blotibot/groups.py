"""Persistent, chat-scoped named groups stored outside the container image."""

from __future__ import annotations

import asyncio
import re
import sqlite3
from collections.abc import Callable, Sequence
from contextlib import closing
from pathlib import Path
from typing import TypeVar

from .models import ALIASES, KNOWN_COMMANDS, Member

T = TypeVar("T")
MAX_GROUPS = 50
MAX_MEMBERS = 500


class GroupError(ValueError):
    """An actionable group-command error safe to show to users."""


def group_name(value: str) -> str:
    name = value.casefold()
    if not re.fullmatch(r"[\w-]{1,32}", name):
        raise GroupError("Use a group name of 1–32 letters, numbers, underscores or hyphens.")
    return name


class GroupStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _run(self, operation: Callable[[sqlite3.Connection], T]) -> T:
        # Every operation owns its connection. SQLite serializes concurrent writers,
        # including workers in different threads, and rolls back failed mutations.
        with closing(sqlite3.connect(self.path, timeout=10)) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                return operation(connection)

    async def initialize(self) -> None:
        def setup() -> None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(self.path)) as connection:
                connection.executescript("""
                    CREATE TABLE IF NOT EXISTS named_groups (
                        chat_id INTEGER NOT NULL,
                        name TEXT NOT NULL,
                        PRIMARY KEY (chat_id, name)
                    );
                    CREATE TABLE IF NOT EXISTS group_members (
                        chat_id INTEGER NOT NULL,
                        name TEXT NOT NULL,
                        user_id INTEGER NOT NULL,
                        first_name TEXT,
                        username TEXT,
                        PRIMARY KEY (chat_id, name, user_id),
                        FOREIGN KEY (chat_id, name) REFERENCES named_groups(chat_id, name)
                            ON DELETE CASCADE
                    );
                """)
            self.path.chmod(0o600)

        await asyncio.to_thread(setup)

    @staticmethod
    def _require(connection: sqlite3.Connection, chat_id: int, name: str) -> None:
        if not connection.execute(
            "SELECT 1 FROM named_groups WHERE chat_id = ? AND name = ?", (chat_id, name)
        ).fetchone():
            raise GroupError("That group does not exist in this chat. Use /groups to list groups.")

    async def create(self, chat_id: int, name: str) -> None:
        name = group_name(name)
        if name in KNOWN_COMMANDS or name in ALIASES:
            raise GroupError("That name is reserved for a bot command. Choose another group name.")

        def operation(connection: sqlite3.Connection) -> None:
            if connection.execute(
                "SELECT 1 FROM named_groups WHERE chat_id = ? AND name = ?", (chat_id, name)
            ).fetchone():
                raise GroupError("That group already exists in this chat.")
            count = connection.execute(
                "SELECT COUNT(*) FROM named_groups WHERE chat_id = ?", (chat_id,)
            ).fetchone()[0]
            if count >= MAX_GROUPS:
                raise GroupError(f"This chat already has the maximum of {MAX_GROUPS} groups.")
            connection.execute("INSERT INTO named_groups VALUES (?, ?)", (chat_id, name))

        await asyncio.to_thread(self._run, operation)

    async def exists(self, chat_id: int, name: str) -> bool:
        name = group_name(name)

        def operation(connection: sqlite3.Connection) -> bool:
            return (
                connection.execute(
                    "SELECT 1 FROM named_groups WHERE chat_id = ? AND name = ?", (chat_id, name)
                ).fetchone()
                is not None
            )

        return await asyncio.to_thread(self._run, operation)

    async def delete(self, chat_id: int, name: str) -> None:
        name = group_name(name)

        def operation(connection: sqlite3.Connection) -> None:
            self._require(connection, chat_id, name)
            connection.execute(
                "DELETE FROM named_groups WHERE chat_id = ? AND name = ?", (chat_id, name)
            )

        await asyncio.to_thread(self._run, operation)

    async def list_groups(self, chat_id: int) -> list[tuple[str, int]]:
        def operation(connection: sqlite3.Connection) -> list[tuple[str, int]]:
            return [
                (str(row[0]), int(row[1]))
                for row in connection.execute(
                    """SELECT g.name, COUNT(m.user_id) FROM named_groups g
                    LEFT JOIN group_members m USING (chat_id, name)
                    WHERE g.chat_id = ? GROUP BY g.name ORDER BY g.name""",
                    (chat_id,),
                )
            ]

        return await asyncio.to_thread(self._run, operation)

    async def members(self, chat_id: int, name: str) -> list[Member]:
        name = group_name(name)

        def operation(connection: sqlite3.Connection) -> list[Member]:
            self._require(connection, chat_id, name)
            return [
                Member(user_id=row[0], first_name=row[1], username=row[2])
                for row in connection.execute(
                    """SELECT user_id, first_name, username FROM group_members
                    WHERE chat_id = ? AND name = ? ORDER BY user_id""",
                    (chat_id, name),
                )
            ]

        return await asyncio.to_thread(self._run, operation)

    async def add(self, chat_id: int, name: str, members: Sequence[Member]) -> int:
        name = group_name(name)

        def operation(connection: sqlite3.Connection) -> int:
            self._require(connection, chat_id, name)
            existing = {
                row[0]
                for row in connection.execute(
                    "SELECT user_id FROM group_members WHERE chat_id = ? AND name = ?",
                    (chat_id, name),
                )
            }
            additions = {member.user_id: member for member in members}
            if len(existing | additions.keys()) > MAX_MEMBERS:
                raise GroupError(f"A group can contain at most {MAX_MEMBERS} members.")
            connection.executemany(
                """INSERT INTO group_members VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (chat_id, name, user_id) DO UPDATE SET
                    first_name = excluded.first_name, username = excluded.username""",
                [(chat_id, name, m.user_id, m.first_name, m.username) for m in additions.values()],
            )
            return len(additions.keys() - existing)

        return await asyncio.to_thread(self._run, operation)

    async def remove(self, chat_id: int, name: str, user_ids: Sequence[int]) -> int:
        name = group_name(name)

        def operation(connection: sqlite3.Connection) -> int:
            self._require(connection, chat_id, name)
            before = connection.total_changes
            connection.executemany(
                "DELETE FROM group_members WHERE chat_id = ? AND name = ? AND user_id = ?",
                [(chat_id, name, user_id) for user_id in set(user_ids)],
            )
            return connection.total_changes - before

        return await asyncio.to_thread(self._run, operation)
