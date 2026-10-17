"""Fast, loud effects."""

from __future__ import annotations

import math
import random
from typing import Any

from ..colormath import hex_to_hs, lerp_hue
from .base import Frame, choice, effect, hsi, num, palette
from .common import Poisson, paint, source_params

CAT = "Party"


@effect(
    "strobe", "Strobe", CAT,
    "Hard on/off flashing. Bluetooth caps the real rate at about 12 Hz.",
    (*source_params("#ffffff", 6500, "white"),
     num("rate", "Rate", 6, 0.5, 12, 0.5, "Hz"),
     num("duty", "On time", 35, 5, 95, 1, "%"),
     num("brightness", "Brightness", 100, 1, 100, 1, "%")),
    accent="#f5f5f5",
)
def strobe(rng: random.Random):
    def step(t: float, p: dict[str, Any]) -> Frame:
        on = (t * p["rate"]) % 1.0 < p["duty"] / 100.0
        return paint(p, p["brightness"] if on else 0)
    return step


@effect(
    "disco", "Disco", CAT,
    "Beat-locked colour jumps with an accent on every downbeat.",
    (num("bpm", "Tempo", 124, 60, 200, 1, "bpm"),
     palette("colors", "Colours", ["#ff006e", "#fb5607", "#ffbe0b", "#3a86ff", "#8338ec"]),
     num("brightness", "Brightness", 90, 1, 100, 1, "%"),
     choice("order", "Order", "random", [("random", "Shuffle"), ("cycle", "In order")]),
     num("punch", "Beat punch", 50, 0, 100, 1)),
    accent="#ff006e",
)
def disco(rng: random.Random):
    state = {"beat": -1, "index": 0}

    def step(t: float, p: dict[str, Any]) -> Frame:
        beat_len = 60.0 / p["bpm"]
        beat = int(t / beat_len)
        colors = p["colors"]
        if beat != state["beat"]:
            state["beat"] = beat
            if p["order"] == "cycle":
                state["index"] = beat % len(colors)
            elif len(colors) > 1:
                state["index"] = (state["index"] + rng.randint(1, len(colors) - 1)) % len(colors)
        hue, sat = hex_to_hs(colors[state["index"] % len(colors)])
        phase = (t % beat_len) / beat_len
        level = p["brightness"] * (1.0 - p["punch"] / 100.0 * 0.6 * phase)
        return hsi(hue, sat, level)
    return step


@effect(
    "cyberpunk", "Cyberpunk", CAT,
    "Magenta and cyan rain-soaked neon, with digital glitches.",
    (num("speed", "Drift", 30, 1, 100, 1),
     num("brightness", "Brightness", 70, 1, 100, 1, "%"),
     num("glitch", "Glitch", 35, 0, 100, 1)),
    accent="#00e5ff",
)
def cyberpunk(rng: random.Random):
    glitches = Poisson(rng)
    state = {"until": -1.0, "hue": 0.0}
    magenta, cyan = 312.0, 187.0

    def step(t: float, p: dict[str, Any]) -> Frame:
        if glitches.due(t, p["glitch"] * 0.6):
            state["until"] = t + rng.uniform(0.05, 0.25)
            state["hue"] = rng.choice([magenta, cyan, 55.0, 270.0])
        if t < state["until"]:
            return hsi(state["hue"], 100, p["brightness"] * rng.uniform(0.2, 1.0))
        f = 0.5 + 0.5 * math.sin(t * p["speed"] / 100.0 * 2.2)
        return hsi(lerp_hue(magenta, cyan, f), 95, p["brightness"])
    return step


@effect(
    "rave", "Rave Chase", CAT,
    "Pure hue jumps on every beat, flashing white on each bar.",
    (num("bpm", "Tempo", 140, 80, 200, 1, "bpm"),
     num("brightness", "Brightness", 100, 1, 100, 1, "%")),
    accent="#c6ff00",
)
def rave(rng: random.Random):
    def step(t: float, p: dict[str, Any]) -> Frame:
        beat_len = 60.0 / p["bpm"]
        beat = int(t / beat_len)
        phase = (t % beat_len) / beat_len
        if beat % 4 == 0 and phase < 0.15:
            return paint({"source": "white", "kelvin": 6500}, p["brightness"])
        return hsi((beat * 137.5) % 360, 100, p["brightness"] * (1 - 0.5 * phase))
    return step
