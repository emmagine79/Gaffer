"""Crossfading between any two light states. Pure.

The light has no transition command, so fades are rendered frame by frame.
Within one mode the native values interpolate (kelvin, hue, channels). Across
modes there is no shared native space, so both ends are expressed as a colour
-- a white as its blackbody hue -- and the fade runs in that space; at the end
the exact target command is sent, so the light lands on the true high-CRI white
rather than an approximation of it.
"""

from __future__ import annotations

from .colormath import hex_to_hs, kelvin_to_hs, lerp, lerp_hue, rgb_to_hsv
from .state import Cct, Hsi, LightState, Rgbw


def _level(state: LightState) -> float:
    return state.brightness if state.power else 0.0


def as_hue_sat(state: LightState) -> tuple[float, float] | None:
    """The state's colour as hue/saturation, or None when it has no fixed colour."""
    if state.mode == "cct":
        return kelvin_to_hs(state.cct.kelvin)
    if state.mode == "hsi":
        return state.hsi.hue, state.hsi.sat
    if state.mode == "rgbw":
        c = state.rgbw
        hue, sat, _ = rgb_to_hsv(tuple(min(1.0, (v + c.w * 0.8) / 1000.0) for v in (c.r, c.g, c.b)))  # type: ignore[arg-type]
        return hue, sat
    if state.mode == "gel" and state.gel is not None:
        return hex_to_hs(state.gel.hex)
    return None


def blend(a: LightState, b: LightState, f: float) -> LightState:
    """The state ``f`` of the way from ``a`` to ``b`` (0 <= f <= 1)."""
    if f >= 1.0:
        return b
    if f <= 0.0:
        return a
    if not a.power and not b.power:
        return b  # nothing to fade; never switch the light on at 0% just to switch it off
    level = round(lerp(_level(a), _level(b), f), 1)
    base = b.model_copy(update={"power": True, "brightness": level})

    # Fading out to off, or in from off, keeps the colour of the lit end.
    if not a.power:
        return base
    if not b.power:
        return a.model_copy(update={"power": True, "brightness": level})

    if a.mode == b.mode == "cct":
        return base.model_copy(update={"cct": Cct(
            kelvin=round(lerp(a.cct.kelvin, b.cct.kelvin, f)),
            gm=round(lerp(a.cct.gm, b.cct.gm, f)),
        )})
    if a.mode == b.mode == "hsi":
        return base.model_copy(update={"hsi": Hsi(
            hue=lerp_hue(a.hsi.hue, b.hsi.hue, f), sat=lerp(a.hsi.sat, b.hsi.sat, f),
        )})
    if a.mode == b.mode == "rgbw":
        return base.model_copy(update={"rgbw": Rgbw(**{
            k: round(lerp(getattr(a.rgbw, k), getattr(b.rgbw, k), f)) for k in "rgbw"
        })})

    ends = as_hue_sat(a), as_hue_sat(b)
    if ends[0] is None or ends[1] is None:
        return b  # an effect has no colour to fade through; cut
    (h1, s1), (h2, s2) = ends  # type: ignore[misc]
    return base.model_copy(update={
        "mode": "hsi",
        "hsi": Hsi(hue=lerp_hue(h1, h2, f), sat=lerp(s1, s2, f)),
    })
