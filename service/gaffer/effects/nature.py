"""Fire, sky and weather."""

from __future__ import annotations

import math
import random
from typing import Any

from ..colormath import clamp, lerp
from .base import Frame, cct, effect, hsi, kelvin, num, toggle
from .common import Poisson, Trigger, noise

CAT = "Nature"


@effect(
    "candle", "Candle", CAT,
    "A real flame in true high-CRI white: soft 1/f flicker, the odd draught, colour that cools as it flares.",
    (kelvin("kelvin", "Flame colour", 1900),
     num("brightness", "Brightness", 55, 1, 100, 1, "%"),
     num("flicker", "Flicker", 55, 0, 100, 1),
     num("wind", "Draughts", 20, 0, 100, 1)),
    accent="#ff9a3c",
)
def candle(rng: random.Random):
    n, fast = noise(rng), noise(rng)
    gusts = Poisson(rng)
    gust = {"until": -1.0, "depth": 0.0}

    def step(t: float, p: dict[str, Any]) -> Frame:
        if gusts.due(t, p["wind"] / 5.0):
            gust["until"] = t + rng.uniform(0.3, 1.2)
            gust["depth"] = rng.uniform(0.15, 0.45) * p["wind"] / 100.0
        f = p["flicker"] / 100.0
        wobble = 0.65 * n.fbm(t * 2.2) + 0.35 * fast(t * 11.0)
        dip = gust["depth"] * math.sin(math.pi * clamp((gust["until"] - t) / 0.8, 0, 1)) if t < gust["until"] else 0.0
        level = p["brightness"] * (1.0 - f * 0.5 * (1.0 - wobble) - dip)
        k = p["kelvin"] + (wobble - 0.5) * 220 * f
        return cct(clamp(k, 1800, 10000), level)
    return step


@effect(
    "fireplace", "Fireplace", CAT,
    "A crackling hearth: deep orange embers with flames that leap and spark.",
    (num("brightness", "Brightness", 60, 1, 100, 1, "%"),
     num("intensity", "Roar", 55, 0, 100, 1),
     num("warmth", "Ember depth", 50, 0, 100, 1, hint="Higher leans red")),
    accent="#ff5a1f",
)
def fireplace(rng: random.Random):
    n, m = noise(rng), noise(rng)
    sparks = Poisson(rng)
    spark = {"at": -9.0}

    def step(t: float, p: dict[str, Any]) -> Frame:
        i = p["intensity"] / 100.0
        if sparks.due(t, 10 + 50 * i):
            spark["at"] = t
        flame = n.fbm(t * (1.5 + 3 * i))
        hue = lerp(32, 8, p["warmth"] / 100.0) + (flame - 0.5) * 16
        pop = 0.22 * math.exp(-(t - spark["at"]) * 14) if t >= spark["at"] else 0.0
        level = p["brightness"] * (0.55 + 0.45 * flame * (0.6 + 0.4 * m(t * 6))) * (1 - 0.3 * (1 - i)) + 100 * pop * i
        return hsi(hue, 92 + 8 * flame, level)
    return step


@effect(
    "storm", "Lightning Storm", CAT,
    "A dark stormy sky with strikes that flicker in bursts. Strike on cue with the trigger.",
    (num("rate", "Strikes / minute", 8, 0, 60, 1),
     num("intensity", "Strike power", 100, 10, 100, 1, "%"),
     kelvin("kelvin", "Strike colour", 7500),
     num("ambient", "Sky level", 4, 0, 30, 1, "%"),
     num("hue", "Sky hue", 222, 180, 270, 1, "°")),
    accent="#9ec5ff",
    trigger="Strike",
)
def storm(rng: random.Random):
    strikes = Poisson(rng)
    cue = Trigger()
    flashes: list[tuple[float, float, float]] = []  # (start, end, level 0-1)

    def schedule(t: float) -> None:
        at = t
        level = 1.0
        for _ in range(rng.randint(2, 5)):
            length = rng.uniform(0.04, 0.13)
            flashes.append((at, at + length, level))
            at += length + rng.uniform(0.04, 0.18)
            level *= rng.uniform(0.45, 0.9)

    def step(t: float, p: dict[str, Any]) -> Frame:
        if strikes.due(t, p["rate"]) or cue.fired(p):
            schedule(t)
        while flashes and flashes[0][1] < t:
            flashes.pop(0)
        for start, end, level in flashes:
            if start <= t <= end:
                return cct(p["kelvin"], p["intensity"] * level)
        return hsi(p["hue"], 70, p["ambient"])
    return step


def _sun(f: float, final_kelvin: float, peak: float) -> Frame:
    """The sky's colour at fraction ``f`` of the way from night to full day."""
    if f < 0.25:
        g = f / 0.25
        return hsi(lerp(0, 14, g), 100, lerp(1, 12, g) * peak / 100)
    if f < 0.55:
        g = (f - 0.25) / 0.30
        return hsi(lerp(14, 34, g), lerp(100, 72, g), lerp(12, 38, g) * peak / 100)
    if f < 0.75:
        g = (f - 0.55) / 0.20
        return cct(lerp(1900, 3200, g), lerp(38, 70, g) * peak / 100)
    g = (f - 0.75) / 0.25
    return cct(lerp(3200, final_kelvin, g), lerp(70, 100, g) * peak / 100)


@effect(
    "sunrise", "Sunrise", CAT,
    "Night to full daylight: deep red, through amber, to clean white. A gentle wake-up light.",
    (num("minutes", "Duration", 15, 0.1, 90, 0.1, "min"),
     kelvin("kelvin", "Daylight", 5600),
     num("peak", "Final brightness", 90, 1, 100, 1, "%"),
     toggle("loop", "Loop", False)),
    accent="#ff7b39",
)
def sunrise(rng: random.Random):
    def step(t: float, p: dict[str, Any]) -> Frame:
        duration = p["minutes"] * 60
        f = (t % duration) / duration if p["loop"] else min(1.0, t / duration)
        return _sun(f, p["kelvin"], p["peak"])
    return step


@effect(
    "sunset", "Sunset", CAT,
    "Daylight easing down through golden hour to a last red glow. Ends nearly dark.",
    (num("minutes", "Duration", 20, 0.1, 120, 0.1, "min"),
     kelvin("kelvin", "Start daylight", 5600),
     num("peak", "Start brightness", 80, 1, 100, 1, "%")),
    accent="#ff4f5e",
)
def sunset(rng: random.Random):
    def step(t: float, p: dict[str, Any]) -> Frame:
        f = 1.0 - min(1.0, t / (p["minutes"] * 60))
        return _sun(f, p["kelvin"], p["peak"])
    return step
