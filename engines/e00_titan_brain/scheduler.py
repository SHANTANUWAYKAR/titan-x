"""
Module: scheduler.py
Description: Async task scheduler for Titan Brain -- one-off delayed
    tasks and recurring interval tasks. Accepts either a sync or async
    callable: sync callables run via asyncio.to_thread so a slow engine
    call (a real network fetch, a CPU-bound backtest) never blocks the
    event loop.

    Governance note: this schedules RESEARCH/ANALYSIS work (signal
    generation, health checks, calibration refreshes) -- there is no
    execution engine in this codebase to schedule trades onto, and if one
    is ever added, it must keep going through the same human-approval gate
    everything else in this platform already requires. This scheduler is a
    plumbing primitive, not an authorization to run anything unattended
    that a human hasn't already approved running on a schedule.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class TaskInfo:
    name: str
    kind: str  # "once" | "interval"
    interval_seconds: Optional[float]
    created_at: datetime
    last_run_at: Optional[datetime] = None
    last_error: Optional[str] = None
    run_count: int = 0


async def _invoke(fn: Callable, *args, **kwargs) -> Any:
    if asyncio.iscoroutinefunction(fn):
        return await fn(*args, **kwargs)
    return await asyncio.to_thread(fn, *args, **kwargs)


class TaskScheduler:
    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}
        self._info: dict[str, TaskInfo] = {}

    def schedule_once(self, name: str, delay_seconds: float, fn: Callable, *args, **kwargs) -> None:
        self.cancel(name)
        self._info[name] = TaskInfo(name=name, kind="once", interval_seconds=None, created_at=datetime.now(timezone.utc))

        async def runner() -> None:
            await asyncio.sleep(delay_seconds)
            await self._run_once(name, fn, *args, **kwargs)

        self._tasks[name] = asyncio.create_task(runner())

    def schedule_interval(self, name: str, interval_seconds: float, fn: Callable, *args, **kwargs) -> None:
        self.cancel(name)
        self._info[name] = TaskInfo(
            name=name, kind="interval", interval_seconds=interval_seconds, created_at=datetime.now(timezone.utc)
        )

        async def runner() -> None:
            while True:
                await self._run_once(name, fn, *args, **kwargs)
                await asyncio.sleep(interval_seconds)

        self._tasks[name] = asyncio.create_task(runner())

    async def _run_once(self, name: str, fn: Callable, *args, **kwargs) -> None:
        info = self._info.get(name)
        try:
            await _invoke(fn, *args, **kwargs)
            if info:
                info.last_error = None
        except Exception as e:
            logger.error("Scheduled task %s failed: %s", name, e)
            if info:
                info.last_error = str(e)
        finally:
            if info:
                info.last_run_at = datetime.now(timezone.utc)
                info.run_count += 1

    def cancel(self, name: str) -> bool:
        task = self._tasks.pop(name, None)
        self._info.pop(name, None)
        if task is not None:
            task.cancel()
            return True
        return False

    async def stop_all(self) -> None:
        for task in self._tasks.values():
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()
        self._info.clear()

    def list_tasks(self) -> list[dict[str, Any]]:
        out = []
        for name, info in self._info.items():
            task = self._tasks.get(name)
            out.append({
                "name": info.name,
                "kind": info.kind,
                "interval_seconds": info.interval_seconds,
                "created_at": info.created_at.isoformat(),
                "last_run_at": info.last_run_at.isoformat() if info.last_run_at else None,
                "last_error": info.last_error,
                "run_count": info.run_count,
                "done": task.done() if task else True,
            })
        return out
