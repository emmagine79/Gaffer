"""Slow, beautiful effects for a room."""

from __future__ import annotations

import math
import random
from typing import Any

from ..colormath import ease, hex_to_hs, lerp, lerp_hue
from .base import Frame, cct, choice, color, effect, hsi, kelvin, num, palette, toggle
from .common import blend_palette, noise, paint, pingpong, source_params

CAT = "Ambient"


@effect(
    "breathe", "Breathe", CAT,
    "A slow inhale and exhale of light. Natural curve lingers at the bottom like real breath.",
    (*source_params("#ff6a3d", 3200),
     num("period", "Breath length", 5, 0.5, 30, 0.1, "s"),
     num("low", "Exhale level", 8, 0, 100, 1, "%"),
     num("high", "Inhale level", 80, 0, 100, 1, "%"),
     choice("curve", "Curve", "natural", [("natural", "Natural"), ("sine", "Sine"), ("sharp", "Sharp")])),
    accent="#ff6a3d",
)
def breathe(rng: random.Random):
    def step(t: float, p: dict[str, Any]) -> Frame:
        s = (1 - math.cos(2 * math.pi * (t / p["period"]))) / 2
        if p["curve"] == "natural":
            s = s**1.7
        elif p["curve"] == "sharp":
            s = s**4
        return paint(p, lerp(p["low"], p["high"], s))
    return step


@effect(
    "heartbeat", "Heartbeat", CAT,
    "A double lub-dub pulse at a resting or racing heart rate.",
    (color("color", "Colour", "#ff1744"),
     num("bpm", "Heart rate", 64, 30, 200, 1, "bpm"),
     num("peak", "Peak", 90, 1, 100, 1, "%"),
     num("rest", "Rest", 6, 0, 60, 1, "%")),
    accent="#ff1744",
)
def heartbeat(rng: random.Random):
    def pulse(x: float, width: float) -> float:
        return math.exp(-((x / width) ** 2))

    def step(t: float, p: dict[str, Any]) -> Frame:
        period = 60.0 / p["bpm"]
        x = t % period
        lub = pulse(x, 0.05)
        dub = 0.65 * pulse(x - 0.26 * min(period, 1.0), 0.06)
        level = p["rest"] + (p["peak"] - p["rest"]) * max(lub, dub)
        hue, sat = hex_to_hs(p["color"])
        return hsi(hue, sat, level)
    return step


@effect(
    "rainbow", "Rainbow", CAT,
    "The full hue wheel, continuously.",
    (num("period", "One lap", 12, 1, 120, 0.5, "s"),
     num("sat", "Saturation", 100, 0, 100, 1, "%"),
     num("brightness", "Brightness", 60, 1, 100, 1, "%"),
     toggle("reverse", "Reverse", False)),
    accent="#7a5cff",
)
def rainbow(rng: random.Random):
    def step(t: float, p: dict[str, Any]) -> Frame:
        direction = -1 if p["reverse"] else 1
        return hsi(direction * 360.0 * t / p["period"], p["sat"], p["brightness"])
    return step


@effect(
    "palette", "Palette Cycle", CAT,
    "Holds each colour of a palette, then glides to the next.",
    (palette("colors", "Palette", ["#ff3d7f", "#ffb347", "#3ddcff", "#7a5cff"]),
     num("hold", "Hold", 3, 0, 60, 0.1, "s"),
     num("fade", "Glide", 2, 0, 30, 0.1, "s"),
     num("brightness", "Brightness", 60, 1, 100, 1, "%"),
     choice("easing", "Glide curve", "inout", [("inout", "Ease in-out"), ("linear", "Linear"), ("out", "Ease out")])),
    accent="#ff3d7f",
)
def palette_cycle(rng: random.Random):
    def step(t: float, p: dict[str, Any]) -> Frame:
        colors = p["colors"]
        n = len(colors)
        segment = max(0.05, p["hold"] + p["fade"])
        index = int(t // segment) % n
        local = t % segment
        h1, s1 = hex_to_hs(colors[index])
        if local <= p["hold"] or p["fade"] <= 0:
            return hsi(h1, s1, p["brightness"])
        h2, s2 = hex_to_hs(colors[(index + 1) % n])
        f = ease(p["easing"], (local - p["hold"]) / p["fade"])
        return hsi(lerp_hue(h1, h2, f), lerp(s1, s2, f), p["brightness"])
    return step


@effect(
    "aurora", "Aurora", CAT,
    "Curtains of green, teal and violet that wander and shimmer like the northern lights.",
    (palette("colors", "Sky", ["#00ff9c", "#00c2ff", "#7a5cff", "#00ff6a"]),
     num("speed", "Drift", 35, 1, 100, 1),
     num("brightness", "Brightness", 55, 1, 100, 1, "%"),
     num("shimmer", "Shimmer", 30, 0, 100, 1)),
    accent="#00ff9c",
)
def aurora(rng: random.Random):
    drift, glow = noise(rng), noise(rng)

    def step(t: float, p: dict[str, Any]) -> Frame:
        speed = p["speed"] / 100.0
        position = drift.fbm(t * speed * 0.35) * len(p["colors"]) * 2.0
        hue, sat = blend_palette(p["colors"], position)
        wave = 0.55 + 0.45 * glow.fbm(t * speed * 0.9 + 40)
        sparkle = 1.0 - p["shimmer"] / 100.0 * 0.25 * glow(t * 9.0 + 100)
        return hsi(hue, sat, p["brightness"] * wave * sparkle)
    return step


@effect(
    "ocean", "Deep Ocean", CAT,
    "Swells of blue and teal, as if lit from under the surface.",
    (num("speed", "Swell speed", 30, 1, 100, 1),
     num("brightness", "Brightness", 55, 1, 100, 1, "%"),
     num("depth", "Depth", 50, 0, 100, 1, hint="Higher is darker and bluer")),
    accent="#0077ff",
)
def ocean(rng: random.Random):
    n = noise(rng)

    def step(t: float, p: dict[str, Any]) -> Frame:
        s = p["speed"] / 100.0
        swell = 0.5 + 0.5 * math.sin(t * s * 1.3) * 0.6 + 0.4 * (n.fbm(t * s * 0.8) - 0.5)
        hue = lerp(178, 228, 0.5 + 0.5 * math.sin(t * s * 0.37 + 1.0)) + p["depth"] * 0.12
        level = p["brightness"] * (0.55 + 0.45 * swell) * (1.0 - p["depth"] / 250.0)
        return hsi(hue, 75 + 20 * swell, level)
    return step


@effect(
    "lava", "Lava Lamp", CAT,
    "Slow molten blobs of red, orange and magenta.",
    (palette("colors", "Wax", ["#ff2a00", "#ff6a00", "#ff0055", "#ffb000"]),
     num("speed", "Speed", 20, 1, 100, 1),
     num("brightness", "Brightness", 60, 1, 100, 1, "%")),
    accent="#ff4d00",
)
def lava(rng: random.Random):
    n, m = noise(rng), noise(rng)

    def step(t: float, p: dict[str, Any]) -> Frame:
        s = p["speed"] / 100.0
        hue, sat = blend_palette(p["colors"], n.fbm(t * s * 0.25) * len(p["colors"]) * 1.6)
        return hsi(hue, sat, p["brightness"] * (0.7 + 0.3 * m.fbm(t * s * 0.6)))
    return step


@effect(
    "golden-hour", "Golden Hour", CAT,
    "Warm late-afternoon white that drifts a little, the way sunlight does through leaves.",
    (kelvin("kelvin", "Warmth", 3000),
     num("drift", "Drift", 40, 0, 100, 1),
     num("brightness", "Brightness", 65, 1, 100, 1, "%"),
     num("gm", "Magenta lift", 6, -30, 30, 1)),
    accent="#ffb347",
)
def golden_hour(rng: random.Random):
    n, m = noise(rng), noise(rng)

    def step(t: float, p: dict[str, Any]) -> Frame:
        d = p["drift"] / 100.0
        k = p["kelvin"] + (n.fbm(t * 0.15) - 0.5) * 700 * d
        level = p["brightness"] * (1.0 - 0.18 * d * m.fbm(t * 0.6))
        return cct(max(1800, min(10000, k)), level, int(p["gm"]))
    return step


@effect(
    "kelvin-sweep", "Kelvin Sweep", CAT,
    "Glides between two whites and back. Good for testing a camera's white balance.",
    (kelvin("warm", "From", 2700), kelvin("cool", "To", 6500),
     num("period", "Round trip", 10, 1, 120, 0.5, "s"),
     num("brightness", "Brightness", 60, 1, 100, 1, "%")),
    accent="#ffd8a8",
)
def kelvin_sweep(rng: random.Random):
    def step(t: float, p: dict[str, Any]) -> Frame:
        f = ease("inout", pingpong(t, p["period"]))
        return cct(lerp(p["warm"], p["cool"], f), p["brightness"])
    return step


@effect(
    "drift", "Two-Tone Drift", CAT,
    "Floats between two colours of your choosing.",
    (color("a", "Colour A", "#ff3d7f"), color("b", "Colour B", "#3ddcff"),
     num("period", "Round trip", 8, 0.5, 120, 0.5, "s"),
     num("brightness", "Brightness", 60, 1, 100, 1, "%"),
     choice("easing", "Curve", "inout", [("inout", "Ease in-out"), ("linear", "Linear")])),
    accent="#3ddcff",
)
def drift(rng: random.Random):
    def step(t: float, p: dict[str, Any]) -> Frame:
        f = ease(p["easing"], pingpong(t, p["period"]))
        h1, s1 = hex_to_hs(p["a"])
        h2, s2 = hex_to_hs(p["b"])
        return hsi(lerp_hue(h1, h2, f), lerp(s1, s2, f), p["brightness"])
    return step
