"""Recreate a gel from its measured colour, for lights without a gel mode.

Godox's catalogue gives every gel's colour. A correction gel (CTO, CTB, plus
or minus green) sits close to the blackbody curve, the line of natural whites:
it is best reproduced as the light's own high-CRI white at the matching colour
temperature, with its distance above or below the curve as green/magenta tint.
A coloured gel sits far from that curve and is reproduced as that colour.
Pure.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from .colormath import hex_to_rgb, rgb_to_hsv

if TYPE_CHECKING:
    from .catalog import ModelCaps

#: Correction gels lie within this distance (CIE 1960 Duv) of the blackbody curve.
WHITE_DUV = 0.035
#: Duv that maps to full tint; a strong plus or minus green is around this.
FULL_TINT_DUV = 0.03
#: Without a tint control a light can only sit on the curve, so only gels this
#: close to it (the CTO and CTB families, as Godox's swatches render them) fit.
NO_TINT_DUV = 0.012
#: How far past its range a gel's temperature may be before a white light
#: would only be clamping it to its end stop.
RANGE_SLACK = 0.1


def _linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _uv(rgb: tuple[float, float, float]) -> tuple[float, float]:
    r, g, b = (_linear(c) for c in rgb)
    x = 0.4124 * r + 0.3576 * g + 0.1805 * b
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = 0.0193 * r + 0.1192 * g + 0.9505 * b
    d = x + 15 * y + 3 * z
    return (4 * x / d, 6 * y / d) if d > 0 else (0.198, 0.312)


def _planck_uv(t: float) -> tuple[float, float]:
    """Krystek's approximation of the blackbody curve, 1000-15000 K."""
    u = (0.860117757 + 1.54118254e-4 * t + 1.28641212e-7 * t * t) / (1 + 8.42420235e-4 * t + 7.08145163e-7 * t * t)
    v = (0.317398726 + 4.22806245e-5 * t + 4.20481691e-8 * t * t) / (1 - 2.89741816e-5 * t + 1.61456053e-7 * t * t)
    return u, v


def cct_duv(rgb: tuple[float, float, float]) -> tuple[float, float]:
    """Nearest colour temperature and the signed distance from the curve (+ is greener)."""
    u, v = _uv(rgb)
    best_t, best_d = 6500.0, math.inf
    t = 1000.0
    while t <= 15000.0:
        pu, pv = _planck_uv(t)
        d = math.hypot(u - pu, v - pv)
        if d < best_d:
            best_t, best_d = t, d
        t *= 1.01
    pv = _planck_uv(best_t)[1]
    return best_t, best_d if v >= pv else -best_d


def _is_white(rgb: tuple[float, float, float]) -> bool:
    _, sat, _ = rgb_to_hsv(rgb)
    _, duv = cct_duv(rgb)
    return abs(duv) <= WHITE_DUV and sat < 75


def emulation_kind(hex_colour: str) -> str:
    """``"white"`` for a correction gel a white light can match, else ``"colour"``."""
    return "white" if _is_white(hex_to_rgb(hex_colour)) else "colour"


def fits_white_light(hex_colour: str, caps: ModelCaps) -> bool:
    """Whether a white-only light can make a fair copy of this gel."""
    rgb = hex_to_rgb(hex_colour)
    if not _is_white(rgb):
        return False
    kelvin, duv = cct_duv(rgb)
    if abs(duv) > (WHITE_DUV if caps.has_tint else NO_TINT_DUV):
        return False
    return caps.min_kelvin * (1 - RANGE_SLACK) <= kelvin <= caps.max_kelvin * (1 + RANGE_SLACK)


def white_for(rgb: tuple[float, float, float], caps: ModelCaps) -> dict[str, Any]:
    """The light's own white nearest to a colour: matching temperature, tint for the rest."""
    kelvin, duv = cct_duv(rgb)
    gm = round(-duv / FULL_TINT_DUV * 100) if caps.has_tint else 0
    return {
        "mode": "cct",
        "kelvin": int(round(max(caps.min_kelvin, min(caps.max_kelvin, kelvin)) / 50) * 50),
        "gm": max(caps.gm_min, min(caps.gm_max, gm)),
    }


def emulate(hex_colour: str, caps: ModelCaps) -> dict[str, Any]:
    """The light state that best reproduces a gel of this colour on ``caps``.

    A light with no colour mode gets the nearest white even for a coloured gel:
    the closest it can come, and the studio only offers it correction gels.
    """
    rgb = hex_to_rgb(hex_colour)
    if not caps.has_colour or (_is_white(rgb) and caps.has_white):
        return white_for(rgb, caps)
    hue, sat, _ = rgb_to_hsv(rgb)
    return {"mode": "hsi", "hue": round(hue) % 360, "sat": round(sat)}
