"""Cue lists: looks stepped through in order with Go.

A cue is stored in the ``cues`` collection as::

    {"id": "interview", "name": "Interview", "steps": [{"look_id": "wide", "fade_seconds": null},
                                                         {"look_id": "close", "fade_seconds": 3.0}]}

A step's ``fade_seconds`` replaces the look's own fade; ``null`` keeps the look's. The hub holds
the active cue and how far it has got (``hub.cue``, in memory: after a restart no cue is active).
``step`` counts the steps run so far: 0 is the top, before the first step, and ``steps`` is the end.

Go runs the next step through ``looks.apply``, so a step does exactly what applying that look does.
Nothing here waits, so two Go presses at once cannot both read the same position.

The same functions serve ``POST /api/cues/{id}/go`` (the Mac shell's Next cue shortcut calls it with
the id ``active``) and the WebSocket commands the page sends (registered below).
"""

from __future__ import annotations

import unicodedata
from typing import Any

from . import looks
from .commands import CommandError, command
from .hub import Client, Hub

COLLECTION = "cues"

#: The id the Mac shell sends to mean "the cue that is running" (contracts/api.md).
ACTIVE = "active"

#: Longest cue name. Same as look names (looks.MAX_NAME).
MAX_NAME = looks.MAX_NAME
#: Longest step fade, seconds. Same bound as a look's fade (looks.MAX_FADE).
MAX_FADE = looks.MAX_FADE
#: Most steps in one cue. Not a product rule: the builder checklist (rule 1) asks for a stated bound so one
#: save cannot be unbounded. Builder's choice, raise it if a real show needs more.
MAX_STEPS = 200


class CueError(CommandError):
    """A refusal with a code for the HTTP answer."""

    def __init__(self, code: str, status: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


def _not_found() -> CueError:
    return CueError("cue_not_found", 404, "There is no cue with that id.")


def _no_active() -> CueError:
    return CueError("no_active_cue", 409, "No cue is running. Start one in the Gaffer window.")


def all_cues(hub: Hub) -> list[dict[str, Any]]:
    """The saved cues. An entry a hand-edit left unreadable is left out, not fatal."""
    sound = []
    for x in hub.store.items(COLLECTION):
        if (isinstance(x, dict) and isinstance(x.get("id"), str) and isinstance(x.get("name"), str)
                and isinstance(x.get("steps"), list)):
            sound.append(x)
    return sound


def find(hub: Hub, cue_id: str) -> dict[str, Any]:
    for cue in all_cues(hub):
        if cue["id"] == cue_id:
            return cue
    raise _not_found()


def view(cue: dict[str, Any]) -> dict[str, Any]:
    """A cue as clients see it."""
    return {"id": cue["id"], "name": cue["name"], "steps": cue["steps"]}


def _steps(cue: dict[str, Any]) -> list[dict[str, Any]]:
    """The steps that are well-formed. A step a hand-edit broke is passed over, not fatal."""
    return [s for s in cue["steps"] if isinstance(s, dict) and isinstance(s.get("look_id"), str)]


def checked(hub: Hub, raw: Any) -> dict[str, Any]:
    """A cue ready to store, or CommandError saying what is wrong. Nothing is stored here."""
    if not isinstance(raw, dict):
        raise CommandError("A cue is an object with a name and steps.")
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise CommandError("A cue needs a name.")
    name = name.strip()
    if len(name) > MAX_NAME:
        raise CommandError(f"A cue name can be at most {MAX_NAME} characters.")
    if any(unicodedata.category(ch) == "Cc" for ch in name):
        raise CommandError("A cue name cannot hold line breaks or control characters.")

    cue_id = raw.get("id")
    if cue_id is None or cue_id == "":
        cue_id = None
    elif (not isinstance(cue_id, str) or len(cue_id) > MAX_NAME or not looks._ID.fullmatch(cue_id)
          or cue_id in looks._RESERVED_IDS or cue_id == ACTIVE):
        raise CommandError("A cue id uses letters, numbers, - and _ only, and cannot be 'active'.")

    steps = raw.get("steps")
    if not isinstance(steps, list) or not steps:
        raise CommandError("A cue needs at least one step.")
    if len(steps) > MAX_STEPS:
        raise CommandError(f"A cue can have at most {MAX_STEPS} steps.")
    known = {look["id"] for look in looks.all_looks(hub)}
    clean = []
    for step in steps:
        if not isinstance(step, dict):
            raise CommandError("A step is an object with a look.")
        look_id = step.get("look_id")
        if not isinstance(look_id, str) or look_id not in known:
            raise CommandError("A step can only use a look that is saved in Gaffer.")
        fade = step.get("fade_seconds")
        if fade is not None and (isinstance(fade, bool) or not isinstance(fade, (int, float)) or not 0 <= fade <= MAX_FADE):
            raise CommandError(f"A step's fade must be empty or a number of seconds from 0 to {MAX_FADE:g}.")
        clean.append({"look_id": look_id, "fade_seconds": None if fade is None else float(fade)})

    if cue_id is None:
        taken = {c["id"] for c in all_cues(hub)}
        base = looks._slug(name) if looks._slug(name) != ACTIVE else "cue"
        cue_id, n = base, 2
        while cue_id in taken or cue_id == ACTIVE:
            cue_id = f"{base}-{n}"
            n += 1
    return {"id": cue_id, "name": name, "steps": clean}


# -- the active cue ------------------------------------------------------------------------


def state(hub: Hub) -> dict[str, Any] | None:
    """The active cue as clients see it: ``{id, name, step, steps}``, or None."""
    if hub.cue is None:
        return None
    try:
        cue = find(hub, hub.cue["id"])
    except CueError:
        return None
    total = len(_steps(cue))
    return {"id": cue["id"], "name": cue["name"], "step": min(hub.cue["step"], total), "steps": total}


def frame(hub: Hub) -> dict[str, Any]:
    """The ``cue`` message. Every field is null when no cue is active."""
    now = state(hub)
    if now is None:
        return {"type": "cue", "id": None, "name": None, "step": None, "steps": None}
    return {"type": "cue", **now}


def _publish(hub: Hub) -> None:
    hub._broadcast(frame(hub))


def _broadcast_store(hub: Hub) -> None:
    hub._broadcast({"type": "store", "collection": COLLECTION, "items": hub.store.items(COLLECTION)})


def start(hub: Hub, cue_id: str) -> dict[str, Any]:
    """Make the cue the active one, at the top. Nothing is applied until Go."""
    cue = find(hub, cue_id)
    if not _steps(cue):
        raise CueError("cue_has_no_steps", 409, "This cue has no steps.")
    hub.cue = {"id": cue["id"], "step": 0}
    _publish(hub)
    return state(hub)  # type: ignore[return-value]


def _run(hub: Hub, cue: dict[str, Any], index: int, direction: int) -> dict[str, Any]:
    """Apply the step at ``index`` (0-based), or the next one in ``direction`` if its look is gone.
    Moves nothing and raises when no step from there can run."""
    steps = _steps(cue)
    while 0 <= index < len(steps):
        step = steps[index]
        try:
            done = looks.apply(hub, step["look_id"], fade=step.get("fade_seconds"))
        except CommandError:  # the look was deleted, or none of its lights is saved any more
            index += direction
            continue
        hub.cue = {"id": cue["id"], "step": index + 1}
        _publish(hub)
        return done
    raise CueError("cue_steps_gone", 409, "None of the looks in this cue can be applied. Edit the cue.")


def go(hub: Hub, cue_id: str | None = None) -> dict[str, Any]:
    """Run the next step. ``cue_id`` None or 'active' means the running cue; another id starts that cue first."""
    if cue_id in (None, ACTIVE):
        if hub.cue is None or state(hub) is None:
            raise _no_active()
        cue = find(hub, hub.cue["id"])
    else:
        cue = find(hub, cue_id)
        if hub.cue is None or hub.cue["id"] != cue["id"]:
            start(hub, cue["id"])
    position = hub.cue["step"]  # type: ignore[index]
    if position >= len(_steps(cue)):
        raise CueError("cue_finished", 409, "That was the last step. Start the cue again to go from the top.")
    done = _run(hub, cue, position, +1)
    return {"look": {"id": done["id"], "name": done["name"]}, "skipped": done["skipped"], "cue": state(hub)}


def back(hub: Hub) -> dict[str, Any]:
    """Step back: apply the step before the one that ran last."""
    if hub.cue is None or state(hub) is None:
        raise _no_active()
    cue = find(hub, hub.cue["id"])
    position = min(hub.cue["step"], len(_steps(cue)))
    if position <= 1:
        raise CueError("cue_at_start", 409, "Already at the first step.")
    done = _run(hub, cue, position - 2, -1)
    return {"look": {"id": done["id"], "name": done["name"]}, "skipped": done["skipped"], "cue": state(hub)}


def save(hub: Hub, raw: Any) -> dict[str, Any]:
    cue = checked(hub, raw)
    stored = hub.store.upsert(COLLECTION, cue)
    _broadcast_store(hub)
    if hub.cue and hub.cue["id"] == stored["id"]:
        _publish(hub)  # renamed, or the steps changed under it
    return stored


def delete(hub: Hub, cue_id: str) -> None:
    cue = find(hub, cue_id)
    hub.store.delete(COLLECTION, cue["id"])
    _broadcast_store(hub)
    if hub.cue and hub.cue["id"] == cue["id"]:
        hub.cue = None
        _publish(hub)


# -- WebSocket commands -------------------------------------------------------------------


@command("cue.start")
async def _start_cue(hub: Hub, client: Client, m: dict[str, Any]) -> dict[str, Any]:
    return {"type": "ack", "of": "cue.start", "cue": start(hub, str(m.get("id") or ""))}


@command("cue.go")
async def _go(hub: Hub, client: Client, m: dict[str, Any]) -> dict[str, Any]:
    return {"type": "ack", "of": "cue.go", **go(hub)}


@command("cue.back")
async def _back(hub: Hub, client: Client, m: dict[str, Any]) -> dict[str, Any]:
    return {"type": "ack", "of": "cue.back", **back(hub)}


@command("cues.save")
async def _save(hub: Hub, client: Client, m: dict[str, Any]) -> dict[str, Any]:
    return {"type": "ack", "of": "cues.save", "cue": view(save(hub, m.get("cue")))}


@command("cues.delete")
async def _delete(hub: Hub, client: Client, m: dict[str, Any]) -> None:
    delete(hub, str(m.get("id") or ""))
