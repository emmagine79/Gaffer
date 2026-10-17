"""Cue lists: looks stepped through in order with Go.

A cue is stored in the ``cues`` collection as::

    {"id": "interview", "name": "Interview", "steps": [{"look_id": "wide", "fade_seconds": null},
                                                         {"look_id": "close", "fade_seconds": 3.0}]}

A step's ``fade_seconds`` replaces the look's own fade; ``null`` keeps the look's. The hub holds
the active cue and how far it has got (``hub.cue``, in memory: after a restart no cue is active).
``step`` counts the steps run so far: 0 is the top, before the first step, and ``steps`` is the end.
Saving the active cue keeps ``step`` only while the steps that have run are unchanged; otherwise the cue
goes back to the top (``_position_after_save``).

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
    elif not looks.valid_id(cue_id, reserved={ACTIVE}):
        raise CommandError("A cue id uses letters, numbers, - and _ only, and cannot be 'active'.")

    steps = raw.get("steps")
    if not isinstance(steps, list) or not steps:
        raise CommandError("A cue needs at least one step.")
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
        cue_id = looks.unique_id(hub, COLLECTION, name, fallback="cue", reserved={ACTIVE})
    return {"id": cue_id, "name": name, "steps": clean}


# -- the active cue ------------------------------------------------------------------------


def _pick(hub: Hub, steps: list[dict[str, Any]], index: int, direction: int) -> int | None:
    """The index of the first step from ``index``, moving by ``direction``, whose look can run (looks.runnable).
    Go, Back and the Go button's label all use this, so the label names the step Go will run."""
    while 0 <= index < len(steps):
        if looks.runnable(hub, steps[index]["look_id"]) is not None:
            return index
        index += direction
    return None


def state(hub: Hub) -> dict[str, Any] | None:
    """The active cue as clients see it: ``{id, name, step, steps, next}``, or None.
    ``next`` is the look the next Go runs, or None at the end or when no remaining step can run."""
    if hub.cue is None:
        return None
    try:
        cue = find(hub, hub.cue["id"])
    except CueError:
        return None
    steps = _steps(cue)
    position = min(hub.cue["step"], len(steps))
    index = _pick(hub, steps, position, +1)
    ahead = looks.runnable(hub, steps[index]["look_id"]) if index is not None else None  # the look Go will run
    return {"id": cue["id"], "name": cue["name"], "step": position, "steps": len(steps),
            "next": {"id": ahead["id"], "name": ahead["name"]} if ahead else None}


def frame(hub: Hub) -> dict[str, Any]:
    """The ``cue`` message. Every field is null when no cue is active."""
    now = state(hub)
    if now is None:
        return {"type": "cue", "id": None, "name": None, "step": None, "steps": None, "next": None}
    return {"type": "cue", **now}


def _publish(hub: Hub) -> None:
    hub._broadcast(frame(hub))


def republish(hub: Hub) -> None:
    """Tell the clients the cue again when one is active (a look it uses was renamed or deleted)."""
    if hub.cue is not None:
        _publish(hub)


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


def _run(hub: Hub, cue: dict[str, Any], index: int, direction: int) -> tuple[dict[str, Any], int]:
    """Apply the step at ``index`` (0-based), or the next one in ``direction`` when its look is gone or has no
    saved light. Returns what ``looks.apply`` returned and the index it ran. Moves no position: the caller sets
    ``hub.cue`` once this has returned. A look whose lights are saved but out of reach is not passed over: the
    Go fails with that look's own answer and the cue stays where it was."""
    steps = _steps(cue)
    picked = _pick(hub, steps, index, direction)
    if picked is None:
        raise CueError("cue_steps_gone", 409, "None of the looks in this cue can be applied. Edit the cue.")
    step = steps[picked]
    try:
        return looks.apply(hub, step["look_id"], fade=step.get("fade_seconds")), picked
    except CommandError as err:
        raise CueError("lights_unreachable", 409, str(err)) from err


def _commit(hub: Hub, cue: dict[str, Any], step: int) -> None:
    hub.cue = {"id": cue["id"], "step": step}
    _publish(hub)


def _answer(hub: Hub, done: dict[str, Any]) -> dict[str, Any]:
    return {"look": {"id": done["id"], "name": done["name"]}, "skipped": done["skipped"], "cue": state(hub)}


def go(hub: Hub, cue_id: str | None = None) -> dict[str, Any]:
    """Run the next step. ``cue_id`` None or 'active' means the running cue; another id runs that cue's first
    step and makes it the active one, but only once that step has run: a Go that fails changes nothing."""
    if cue_id in (None, ACTIVE):
        if hub.cue is None or state(hub) is None:
            raise _no_active()
        cue = find(hub, hub.cue["id"])
        position = hub.cue["step"]
    else:
        cue = find(hub, cue_id)
        position = hub.cue["step"] if hub.cue is not None and hub.cue["id"] == cue["id"] else 0
    total = len(_steps(cue))
    if total == 0:
        raise CueError("cue_has_no_steps", 409, "This cue has no steps.")
    if position >= total:
        raise CueError("cue_finished", 409, "That was the last step. Start the cue again to go from the top.")
    done, index = _run(hub, cue, position, +1)
    _commit(hub, cue, index + 1)
    return _answer(hub, done)


def back(hub: Hub) -> dict[str, Any]:
    """Step back: apply the step before the one that ran last."""
    if hub.cue is None or state(hub) is None:
        raise _no_active()
    cue = find(hub, hub.cue["id"])
    position = min(hub.cue["step"], len(_steps(cue)))
    if position <= 1:
        raise CueError("cue_at_start", 409, "Already at the first step.")
    done, index = _run(hub, cue, position - 2, -1)
    _commit(hub, cue, index + 1)
    return _answer(hub, done)


def _position_after_save(hub: Hub, new: dict[str, Any]) -> int:
    """Where the active cue sits once ``new`` replaces it. The position is a count of steps run, so it stays
    right only while those steps are the same ones in the same order (look and fade); if any of them was
    changed, removed or has another step in front of it, the cue goes back to the top rather than run the
    wrong step. Renaming, and editing the steps still to come, keep the position."""
    if hub.cue is None or hub.cue["id"] != new["id"]:
        return 0
    try:
        old = _steps(find(hub, new["id"]))
    except CueError:
        return 0
    run = min(hub.cue["step"], len(old))

    def same(step: dict[str, Any]) -> tuple[Any, Any]:
        return step["look_id"], step.get("fade_seconds")

    return run if [same(s) for s in old[:run]] == [same(s) for s in new["steps"][:run]] else 0


def save(hub: Hub, raw: Any) -> dict[str, Any]:
    cue = checked(hub, raw)
    position = _position_after_save(hub, cue)
    stored = hub.store.upsert(COLLECTION, cue)
    _broadcast_store(hub)
    if hub.cue and hub.cue["id"] == stored["id"]:
        _commit(hub, stored, position)  # renamed, or the steps changed under it
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
