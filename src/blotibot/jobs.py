"""Per-chat job lifecycle and cancellation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum, auto


@dataclass(slots=True)
class Job:
    cancelled: asyncio.Event = field(default_factory=asyncio.Event)


class StartResult(Enum):
    STARTED = auto()
    ALREADY_RUNNING = auto()
    AT_CAPACITY = auto()


class JobRegistry:
    def __init__(self, max_active_chats: int) -> None:
        self._max_active_chats = max_active_chats
        self._jobs: dict[int, Job] = {}
        self._lock = asyncio.Lock()

    async def try_start(self, chat_id: int) -> tuple[StartResult, Job | None]:
        async with self._lock:
            if chat_id in self._jobs:
                return StartResult.ALREADY_RUNNING, None
            if len(self._jobs) >= self._max_active_chats:
                return StartResult.AT_CAPACITY, None
            job = Job()
            self._jobs[chat_id] = job
            return StartResult.STARTED, job

    async def finish(self, chat_id: int, job: Job) -> None:
        async with self._lock:
            if self._jobs.get(chat_id) is job:
                del self._jobs[chat_id]

    async def cancel(self, chat_id: int) -> bool:
        async with self._lock:
            job = self._jobs.get(chat_id)
            if job is None:
                return False
            job.cancelled.set()
            return True

    async def is_running(self, chat_id: int) -> bool:
        async with self._lock:
            return chat_id in self._jobs
