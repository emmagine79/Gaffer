"""Looks: saved settings for many lights, each look with its own fade.

A look is stored in the ``looks`` collection as::

    {"id": "talking-head", "name": "Talking head", "fade_seconds": 2.0,
     "lights": {"<light id>": {<state patch>}, ...}}

Applying a look runs every light in it to its patch with lumen's ``_start``: a fade of
0 sets the light at once, anything longer starts ``engine.start_transition``. Every
light's values are worked out first and the lights are started only after that, so a
look is never half applied. A light that is not saved, not on the network or cannot
take its patch is left alone and named in ``skipped``. The list order is the slot
order: slot 1 is the first look (the Mac shortcuts and keys 1 to 9).

The same functions serve the HTTP routes the Mac shell calls (``app.py``) and the
WebSocket commands the web page sends (registered below).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from .commands import CommandError, _fitted, _start, command
from .hub import Client, Hub

COLLECTION = "looks"

#: Longest look name. Same as the project's other user-facing names (store.py: gel names under 80).
MAX_NAME = 80
#: Longest fade, seconds. The project's own bound for fades: store.py SETTING_RULES["default_fade"].
MAX_FADE = 60.0

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
_RESERVED_IDS = frozenset({"__proto__", "constructor", "prototype"})


class LookNotFound(CommandError):
    """No look has that id."""


def _slug(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")[:MAX_NAME] or "look"


def _valid_id(look_id: Any) -> bool:
    """The one rule for a look id, whether the client sent it or we made it from the name."""
    return isinstance(look_id, str) and len(look_id) <= MAX_NAME and bool(_ID.fullmatch(look_id)) and look_id not in _RESERVED_IDS


def _unique_id(hub: Hub, name: str) -> str:
    # Every id in the file counts, also those of entries a hand-edit left unreadable: all_looks hides
    # those, and a new look must not take their id and overwrite them.
    taken = {x["id"] for x in hub.store.items(COLLECTION) if isinstance(x, dict) and isinstance(x.get("id"), str)}
    base = _slug(name)
    candidate, n = base, 2
    while candidate in taken or not _valid_id(candidate):
        suffix = f"-{n}"
        candidate = base[: MAX_NAME - len(suffix)].rstrip("-") + suffix  # still within the id length limit
        n += 1
    return candidate


def view(look: dict[str, Any]) -> dict[str, Any]:
    """A look as clients see it."""
    return {"id": look["id"], "name": look["name"], "fade_seconds": look["fade_seconds"], "lights": look["lights"]}


def all_looks(hub: Hub) -> list[dict[str, Any]]:
    """The saved looks in slot order. An entry a hand-edit left unreadable is left out, not fatal."""
    sound = []
    for x in hub.store.items(COLLECTION):
        if (isinstance(x, dict) and isinstance(x.get("id"), str) and isinstance(x.get("name"), str)
                and isinstance(x.get("lights"), dict) and isinstance(x.get("fade_seconds"), (int, float))):
            sound.append(x)
    return sound


def find(hub: Hub, look_id: str) -> dict[str, Any]:
    for look in all_looks(hub):
        if look["id"] == look_id:
            return look
    raise LookNotFound("There is no look with that id.")


def capture(hub: Hub) -> dict[str, dict[str, Any]]:
    """What every light is doing now, as a look's ``lights``."""
    return {f.id: f.state.model_dump() for f in hub.fixtures.values()}


def checked(hub: Hub, raw: Any) -> dict[str, Any]:
    """A look ready to store, or CommandError saying what is wrong. Nothing is stored here."""
    if not isinstance(raw, dict):
        raise CommandError("A look is an object with a name.")
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise CommandError("A look needs a name.")
    name = name.strip()
    if len(name) > MAX_NAME:
        raise CommandError(f"A look name can be at most {MAX_NAME} characters.")
    if any(unicodedata.category(ch) == "Cc" for ch in name):
        raise CommandError("A look name cannot hold line breaks or control characters.")

    existing: dict[str, Any] | None = None
    look_id = raw.get("id")
    if look_id is None or look_id == "":
        look_id = None
    else:
        if not _valid_id(look_id):
            raise CommandError("A look id uses letters, numbers, - and _ only.")
        existing = next((x for x in all_looks(hub) if x["id"] == look_id), None)

    fade = raw.get("fade_seconds", existing["fade_seconds"] if existing else hub.store.settings["default_fade"])
    if isinstance(fade, bool) or not isinstance(fade, (int, float)) or not 0 <= fade <= MAX_FADE:
        raise CommandError(f"The fade must be a number of seconds from 0 to {MAX_FADE:g}.")

    if raw.get("capture") or ("lights" not in raw and existing is None):
        lights = capture(hub)
    elif "lights" in raw:
        lights = raw["lights"]
    else:
        lights = existing["lights"]  # type: ignore[index]
    if not isinstance(lights, dict) or not lights:
        raise CommandError("A look needs at least one light.")
    for light_id, patch in lights.items():
        fixture = hub.fixtures.get(light_id) if isinstance(light_id, str) else None
        if fixture is None:
            raise CommandError("A look can only name lights that are saved in Gaffer.")
        _fitted(fixture, patch)  # the light can take it, or this raises now rather than at apply time

    return {"id": look_id or _unique_id(hub, name), "name": name, "fade_seconds": float(fade), "lights": lights}


def set_current(hub: Hub, look: dict[str, Any] | None) -> None:
    """Note which look is on now and tell every client (and the Mac menu bar)."""
    hub.look = {"id": look["id"], "name": look["name"]} if look else None
    hub._broadcast(frame(hub))


def frame(hub: Hub) -> dict[str, Any]:
    """The ``look`` message: the current look's name (None when no look is on)."""
    return {"type": "look", "id": hub.look["id"] if hub.look else None, "name": hub.look["name"] if hub.look else None}


def _broadcast_store(hub: Hub) -> None:
    hub._broadcast({"type": "store", "collection": COLLECTION, "items": hub.store.items(COLLECTION)})


def save(hub: Hub, raw: Any) -> dict[str, Any]:
    look = checked(hub, raw)
    stored = hub.store.upsert(COLLECTION, look)
    _broadcast_store(hub)
    if hub.look and hub.look["id"] == stored["id"] and hub.look["name"] != stored["name"]:
        set_current(hub, stored)  # renamed while on: the menu bar must show the new name
    return stored


def delete(hub: Hub, look_id: str) -> None:
    look = find(hub, look_id)
    hub.store.delete(COLLECTION, look["id"])
    _broadcast_store(hub)
    if hub.look and hub.look["id"] == look["id"]:
        set_current(hub, None)


def apply(hub: Hub, look_id: str, fade: float | None = None) -> dict[str, Any]:
    """Run every light in the look to its values. A light that is not saved, not on the network or
    cannot take its part is skipped and named in ``skipped``; the others still move. Every target is
    worked out before any light starts, so a failure there leaves all lights and the current look as
    they were. Raises CommandError when no light could move.
    ``fade`` replaces the look's own fade for this run (a cue step's fade, SPEC-014)."""
    look = find(hub, look_id)
    fade = float(look["fade_seconds"] if fade is None else fade)
    skipped: list[str] = []
    plan = []
    for light_id, patch in look["lights"].items():
        fixture = hub.fixtures.get(light_id)
        if fixture is None or not hub.on_network(fixture):
            skipped.append(light_id)
            continue
        try:
            plan.append((fixture, _fitted(fixture, patch)))
        except CommandError:
            skipped.append(light_id)
    if not plan:
        raise CommandError("None of the lights in this look can be reached right now.")
    for fixture, target in plan:
        fixture.stream_source = None  # a look takes the light over, like any command
        _start(hub, fixture, target, fade)
    set_current(hub, look)
    return {"id": look["id"], "name": look["name"], "skipped": skipped}


async def all_off(hub: Hub) -> list[str]:
    """Every light off at once. Returns the ids of the lights it could not reach (not on the network):
    it leaves those alone, and when one of them is on the current look stays, because not everything is off."""
    for fixture in hub.fixtures.values():
        if hub.on_network(fixture):
            fixture.stream_source = None
    await hub.power_all(False)  # lumen: stops each light's engine, then sets power off at once
    unreached = [f for f in hub.fixtures.values() if not hub.on_network(f)]
    if not any(f.state.power for f in unreached):
        set_current(hub, None)
    return [f.id for f in unreached]


# -- WebSocket commands -------------------------------------------------------------------


@command("looks.apply")
async def _apply(hub: Hub, client: Client, m: dict[str, Any]) -> dict[str, Any]:
    return {"type": "ack", "of": "looks.apply", **apply(hub, str(m.get("id") or ""))}


@command("looks.save")
async def _save(hub: Hub, client: Client, m: dict[str, Any]) -> dict[str, Any]:
    return {"type": "ack", "of": "looks.save", "look": view(save(hub, m.get("look")))}


@command("looks.delete")
async def _delete(hub: Hub, client: Client, m: dict[str, Any]) -> None:
    delete(hub, str(m.get("id") or ""))


@command("all.off")
async def _all_off(hub: Hub, client: Client, m: dict[str, Any]) -> None:
    await all_off(hub)
