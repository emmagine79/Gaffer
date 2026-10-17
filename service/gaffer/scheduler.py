"""Timed actions: sunrise alarms, scenes at a time, lights out.

Schedules live in the store's ``schedules`` collection:

    {"name", "enabled", "at": "HH:MM", "days": [0-6, Monday = 0],
     "action": "scene" | "effect" | "sunrise" | "off" | "on",
     "target": scene id or effect id, "minutes": sunrise length}

A schedule fires once in the minute it names, local time. Runs while the
studio is running; there is no service that wakes the computer.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


def due(schedule: dict[str, Any], now: datetime) -> bool:
    if not schedule.get("enabled", True):
        return False
    try:
        hour, minute = (int(x) for x in str(schedule.get("at", "")).split(":"))
    except ValueError:
        return False
    days = schedule.get("days") or list(range(7))
    return now.weekday() in days and now.hour == hour and now.minute == minute


async def run_scheduler(
    items: Callable[[], list[dict[str, Any]]],
    fire: Callable[[dict[str, Any]], None],
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC).astimezone(),  # local wall-clock time
    interval: float = 10.0,
) -> None:
    fired: set[str] = set()
    while True:
        now = clock()
        stamp = now.strftime("%Y-%m-%d %H:%M")
        for schedule in items():
            try:
                key = f"{schedule.get('id')}|{stamp}"
                if key in fired or not due(schedule, now):
                    continue
                fired.add(key)
                fire(schedule)
            except Exception:
                # One malformed or failing schedule must not stop the others.
                logger.exception("schedule %s failed", schedule.get("name") if isinstance(schedule, dict) else schedule)
        fired = {k for k in fired if k.endswith(stamp)}
        await asyncio.sleep(interval)
