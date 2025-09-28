"""Simple scheduler for delayed tasks."""
from __future__ import annotations

import asyncio
import heapq
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Coroutine, Optional


@dataclass(order=True)
class ScheduledTask:
    execute_at: float
    callback: Callable[[], Awaitable[None]] = field(compare=False)
    id: str = field(default_factory=lambda: str(time.time()), compare=False)


class TaskScheduler:
    """Lightweight scheduler for delayed async callbacks."""

    def __init__(self) -> None:
        self._tasks: list[ScheduledTask] = []
        self._event = asyncio.Event()
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        asyncio.create_task(self._runner())

    async def stop(self) -> None:
        self._running = False
        self._event.set()

    async def schedule(self, delay_seconds: float, callback: Callable[[], Awaitable[None]]) -> None:
        execute_at = time.time() + delay_seconds
        heapq.heappush(self._tasks, ScheduledTask(execute_at, callback))
        self._event.set()

    async def _runner(self) -> None:
        while self._running:
            now = time.time()
            if not self._tasks:
                self._event.clear()
                await self._event.wait()
                continue
            next_task = self._tasks[0]
            if next_task.execute_at > now:
                wait_time = min(next_task.execute_at - now, 10.0)
                try:
                    await asyncio.wait_for(self._event.wait(), timeout=wait_time)
                except asyncio.TimeoutError:
                    pass
                self._event.clear()
                continue
            heapq.heappop(self._tasks)
            try:
                await next_task.callback()
            except Exception:  # pragma: no cover - defensive logging
                import logging

                logging.getLogger(__name__).exception("Scheduled task failed")


__all__ = ["TaskScheduler"]
