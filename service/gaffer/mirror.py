"""Copying one light's look onto another, property by property. Pure.

"Sync all lights" is a set of properties (power, brightness, white, colour,
effects) and a set of lights. When any member changes, the others take the
chosen properties from it, each fitted to its own model: a bi-colour light
follows a colour as the matching warmth, a narrower light clamps a
temperature to its own range, and a built-in effect is matched by name,
because the same effect has a different number on different generations.
"""

from __future__ import annotations

from typing import Any

from .adapt import adapt_state
from .catalog import ModelCaps
from .colormath import clamp
from .state import Fx, LightState

ALL_PROPS: frozenset[str] = frozenset({"power", "brightness", "white", "colour", "effects"})
COLOUR_MODES = ("hsi", "rgbw", "gel")


def _matching_effect(leader: LightState, caps: ModelCaps, leader_caps: ModelCaps | None) -> Fx | None:
    if leader.fx is None or leader_caps is None:
        return None
    ours = next((e for e in leader_caps.effects if e.symbol == leader.fx.symbol), None)
    if ours is None:
        return None
    theirs = next((e for e in caps.effects if e.name.lower() == ours.name.lower()), None)
    if theirs is None:
        return None
    allowed = {p["key"] for p in theirs.params}
    speed = None if leader.fx.speed is None else int(clamp(leader.fx.speed, 0, theirs.speed_max))
    return Fx(symbol=theirs.symbol, speed=speed, params={k: v for k, v in leader.fx.params.items() if k in allowed})


def mirror(
    leader: LightState,
    follower: LightState,
    props: frozenset[str],
    caps: ModelCaps,
    *,
    leader_caps: ModelCaps | None = None,
) -> LightState:
    """``follower`` with ``props`` taken from ``leader``, fitted to ``caps``."""
    update: dict[str, Any] = {}
    if "power" in props:
        update["power"] = leader.power
    if "brightness" in props:
        update["brightness"] = leader.brightness
    if leader.mode == "cct" and "white" in props:
        update.update(mode="cct", cct=leader.cct)
    elif leader.mode in COLOUR_MODES and "colour" in props:
        update.update(mode=leader.mode, **{leader.mode: getattr(leader, leader.mode)})
    elif leader.mode == "fx" and "effects" in props:
        fx = _matching_effect(leader, caps, leader_caps)
        if fx is not None:
            update.update(mode="fx", fx=fx)
    if not update:
        return adapt_state(follower, caps)
    return adapt_state(follower.model_copy(update=update), caps)
