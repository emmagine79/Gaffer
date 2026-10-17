"""Schedules: a look, or all off, at a time on chosen days of the week.

A schedule is stored in the ``schedules`` collection as::

    {"id", "name", "enabled": true, "at": "22:00", "days": [0, 1, 2, 3, 4],
     "action": "look" | "off", "target": "<look id>"   (the look action only)}

Days count from Monday = 0. lumen's ``scheduler.py`` decides when one is due and fires it
(``due()``, ``run_scheduler(clock=...)``); ``Hub.fire_schedule`` runs it with
``looks.apply`` or ``looks.all_off``. Saving goes through here so a bad schedule never
reaches the disk; the generic ``store.upsert`` refuses the collection.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from .commands import CommandError, command
from .hub import Client, Hub
from .looks import MAX_NAME, _ID, _RESERVED_IDS, find as find_look

COLLECTION = "schedules"
ACTIONS = ("look", "off")

_TIME = re.compile(r"([01][0-9]|2[0-3]):([0-5][0-9])")  # ASCII digits only: \d would take full-width ones


def checked(hub: Hub, raw: Any) -> dict[str, Any]:
    """A schedule ready to store, or CommandError saying what is wrong. Nothing is stored here."""
    if not isinstance(raw, dict):
        raise CommandError("A schedule is an object with a name.")
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise CommandError("A schedule needs a name.")
    name = name.strip()
    if len(name) > MAX_NAME:
        raise CommandError(f"A schedule name can be at most {MAX_NAME} characters.")
    if any(unicodedata.category(ch) == "Cc" for ch in name):
        raise CommandError("A schedule name cannot hold line breaks or control characters.")

    schedule_id = raw.get("id")
    if schedule_id in (None, ""):
        schedule_id = None
    elif (not isinstance(schedule_id, str) or len(schedule_id) > MAX_NAME or not _ID.fullmatch(schedule_id)
          or schedule_id in _RESERVED_IDS):
        raise CommandError("A schedule id uses letters, numbers, - and _ only.")

    at = raw.get("at")
    if not isinstance(at, str) or not _TIME.fullmatch(at):
        raise CommandError("The time must look like 22:00 (24-hour clock).")

    days = raw.get("days")
    if (not isinstance(days, list) or not days or len(days) > 7
            or not all(isinstance(d, int) and not isinstance(d, bool) and 0 <= d <= 6 for d in days)
            or len(set(days)) != len(days)):
        raise CommandError("Pick at least one day. Days run from 0 (Monday) to 6 (Sunday).")

    enabled = raw.get("enabled", True)
    if not isinstance(enabled, bool):
        raise CommandError("Enabled is true or false.")

    action = raw.get("action")
    if action not in ACTIONS:
        raise CommandError("A schedule either applies a look or turns everything off.")
    item: dict[str, Any] = {"name": name, "enabled": enabled, "at": at, "days": sorted(days), "action": action}
    if schedule_id:
        item["id"] = schedule_id
    if action == "look":
        target = raw.get("target")
        if not isinstance(target, str) or not target:
            raise CommandError("Choose the look to apply.")
        if enabled:  # a paused schedule can be saved after its look is deleted; turning it on again needs the look
            find_look(hub, target)  # raises "There is no look with that id."
        item["target"] = target
    return item


def save(hub: Hub, raw: Any) -> dict[str, Any]:
    item = checked(hub, raw)
    before = next((x for x in hub.store.items(COLLECTION) if isinstance(x, dict) and x.get("id") == item.get("id")), None)
    if before is not None and "created" in before:
        item["created"] = before["created"]  # saving over a schedule keeps when it was made
    stored = hub.store.upsert(COLLECTION, item)
    _broadcast_store(hub)
    return stored


def delete(hub: Hub, schedule_id: str) -> None:
    hub.store.delete(COLLECTION, schedule_id)
    _broadcast_store(hub)


def _broadcast_store(hub: Hub) -> None:
    hub._broadcast({"type": "store", "collection": COLLECTION, "items": hub.store.items(COLLECTION)})


@command("schedules.save")
async def _save(hub: Hub, client: Client, m: dict[str, Any]) -> dict[str, Any]:
    return {"type": "ack", "of": "schedules.save", "schedule": save(hub, m.get("schedule"))}


@command("schedules.delete")
async def _delete(hub: Hub, client: Client, m: dict[str, Any]) -> None:
    delete(hub, str(m.get("id") or ""))
