"""Helpers shared by the effect families."""

from __future__ import annotations

import math
import random
from typing import Any

from ..colormath import ValueNoise, hex_to_hs, kelvin_to_hs, lerp, lerp_hue
from .base import Frame, Param, cct, choice, color, hsi, kelvin


def noise(rng: random.Random, size: int = 256) -> ValueNoise:
    return ValueNoise([rng.random() for _ in range(size)])


def source_params(default_color: str, default_kelvin: int, default_source: str = "color") -> tuple[Param, ...]:
    """The 'colour or white?' trio many effects share."""
    return (
        choice("source", "Light source", default_source, [("color", "Colour"), ("white", "White (high CRI)")]),
        color("color", "Colour", default_color),
        kelvin("kelvin", "White temperature", default_kelvin),
    )


def paint(p: dict[str, Any], brightness: float) -> Frame:
    """Render the shared source params at a brightness."""
    if p.get("source") == "white":
        return cct(p["kelvin"], brightness)
    hue, sat = hex_to_hs(p["color"])
    return hsi(hue, sat, brightness)


def blend_palette(colors: list[str], position: float) -> tuple[float, float]:
    """Hue and saturation at a fractional position along a looping palette."""
    if not colors:
        return 0.0, 0.0
    n = len(colors)
    position %= n
    i = math.floor(position)
    f = position - i
    h1, s1 = hex_to_hs(colors[i % n])
    h2, s2 = hex_to_hs(colors[(i + 1) % n])
    f = f * f * (3 - 2 * f)
    return lerp_hue(h1, h2, f), lerp(s1, s2, f)


def pingpong(t: float, period: float) -> float:
    """0 -> 1 -> 0 over ``period`` seconds."""
    if period <= 0:
        return 0.0
    phase = (t / period) % 1.0
    return 1.0 - abs(2.0 * phase - 1.0)


def kelvin_hsi(k: float, brightness: float) -> Frame:
    """A white expressed as colour, for blending a white into a colour."""
    hue, sat = kelvin_to_hs(k)
    return hsi(hue, sat, brightness)


class Poisson:
    """Random events at an average rate, scheduled ahead so they are seed-stable."""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.next_at = 0.0

    def due(self, t: float, per_minute: float) -> bool:
        if per_minute <= 0:
            return False
        if self.next_at == 0.0:
            self.next_at = t + self.rng.expovariate(per_minute / 60.0)
        if t >= self.next_at:
            self.next_at = t + self.rng.expovariate(per_minute / 60.0)
            return True
        return False


class Trigger:
    """Fires once each time the UI bumps the ``_trigger`` counter."""

    def __init__(self) -> None:
        self.seen: int | None = None

    def fired(self, p: dict[str, Any]) -> bool:
        count = int(p.get("_trigger", 0))
        if self.seen is None:
            self.seen = count
            return False
        if count != self.seen:
            self.seen = count
            return True
        return False
