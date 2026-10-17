"""Effects that only make sense with a computer driving the light frame by frame."""

from __future__ import annotations

import itertools
import math
import random
from typing import Any

from ..colormath import clamp, ease, hex_to_hs, hex_to_rgb, kelvin_to_hs, lerp, lerp_hue, rgb_to_hsv
from .base import Frame, Param, cct, choice, effect, hsi, kelvin, num, toggle
from .common import Poisson, Trigger, noise, paint, source_params

CAT = "Signature"


def text(key: str, label: str, default: str, hint: str = "") -> Param:
    return Param(key, label, "text", default, hint=hint)


# -- photo booth --------------------------------------------------------------------------


@effect(
    "photo-booth", "Photo Booth", CAT,
    "A soft modelling light. Press Count down: three blinks, then a full-power flash on zero, for self-timer shots.",
    (kelvin("kelvin", "Flash colour", 5600),
     num("model", "Modelling light", 20, 1, 60, 1, "%"),
     num("flash", "Flash power", 100, 10, 100, 1, "%"),
     num("count", "Count from", 3, 1, 10, 1, "s")),
    accent="#fff4e0",
    trigger="Count down",
)
def photo_booth(rng: random.Random):
    cue = Trigger()
    state = {"start": None}

    def step(t: float, p: dict[str, Any]) -> Frame:
        if cue.fired(p):
            state["start"] = t
        start = state["start"]
        if start is not None:
            x = t - start
            count = p["count"]
            if x < count:
                blink = (x % 1.0) < 0.15
                return cct(p["kelvin"], p["model"] + (35 if blink else 0))
            if x < count + 0.25:
                return cct(p["kelvin"], p["flash"])
            if x < count + 1.2:
                return cct(p["kelvin"], lerp(p["flash"] * 0.3, p["model"], (x - count - 0.25) / 0.95))
            state["start"] = None
        return cct(p["kelvin"], p["model"])
    return step


# -- hyperspace -------------------------------------------------------------------------------


@effect(
    "hyperspace", "Hyperspace", CAT,
    "Cruising through deep space. Press Jump: the stars stretch, everything blurs to white, and you drop out somewhere new.",
    (num("cruise", "Cruise level", 8, 1, 40, 1, "%"),
     num("peak", "Jump flash", 100, 20, 100, 1, "%"),
     num("build", "Spool-up", 2.5, 0.5, 8, 0.1, "s")),
    accent="#7fb2ff",
    trigger="Jump",
)
def hyperspace(rng: random.Random):
    cue = Trigger()
    twinkle = noise(rng)
    state = {"start": None, "arrive_hue": 222.0}

    def step(t: float, p: dict[str, Any]) -> Frame:
        if cue.fired(p) and state["start"] is None:
            state["start"] = t
            state["arrive_hue"] = rng.choice([222.0, 265.0, 190.0, 300.0])
        start = state["start"]
        base = p["cruise"] * (0.75 + 0.25 * twinkle(t * 3))
        if start is None:
            return hsi(222, 80, base)
        x = t - start
        build = p["build"]
        if x < build:
            f = (x / build) ** 2.2
            flicker = 1 - 0.25 * f * (rng.random() > 0.6)
            return hsi(lerp_hue(222, 210, f), lerp(80, 8, f), lerp(base, p["peak"] * 0.7, f) * flicker)
        if x < build + 0.25:
            return cct(9000, p["peak"])
        if x < build + 2.0:
            f = ease("out", (x - build - 0.25) / 1.75)
            return hsi(state["arrive_hue"], lerp(10, 80, f), lerp(p["peak"] * 0.6, p["cruise"], f))
        state["start"] = None
        return hsi(state["arrive_hue"], 80, base)
    return step


# -- morse ------------------------------------------------------------------------------------

_MORSE = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".", "F": "..-.", "G": "--.", "H": "....", "I": "..",
    "J": ".---", "K": "-.-", "L": ".-..", "M": "--", "N": "-.", "O": "---", "P": ".--.", "Q": "--.-", "R": ".-.",
    "S": "...", "T": "-", "U": "..-", "V": "...-", "W": ".--", "X": "-..-", "Y": "-.--", "Z": "--..",
    "0": "-----", "1": ".----", "2": "..---", "3": "...--", "4": "....-", "5": ".....", "6": "-....",
    "7": "--...", "8": "---..", "9": "----.", ".": ".-.-.-", ",": "--..--", "?": "..--..", "!": "-.-.--",
}


def morse_timeline(message: str) -> list[tuple[bool, int]]:
    """(on, units) segments for a message: dot 1, dash 3, gaps 1 / 3 / 7, then a long rest."""
    segments: list[tuple[bool, int]] = []
    for w, word in enumerate(message.upper().split()):
        if w:
            segments.append((False, 7))
        letters = [c for c in word if c in _MORSE]
        for i, ch in enumerate(letters):
            if i:
                segments.append((False, 3))
            for j, sym in enumerate(_MORSE[ch]):
                if j:
                    segments.append((False, 1))
                segments.append((True, 1 if sym == "." else 3))
    segments.append((False, 14))
    return segments


@effect(
    "morse", "Morse Message", CAT,
    "Spells out your message in Morse code, on a loop.",
    (text("message", "Message", "HELLO RITIK", hint="Letters, numbers and . , ? !"),
     num("wpm", "Speed", 10, 3, 30, 1, "wpm"),
     *source_params("#ffb347", 4300, "white"),
     num("brightness", "Brightness", 70, 1, 100, 1, "%"),
     num("floor", "Between symbols", 2, 0, 30, 1, "%")),
    accent="#ffb347",
)
def morse(rng: random.Random):
    cache: dict[str, Any] = {"message": None, "segments": [], "units": 1}

    def step(t: float, p: dict[str, Any]) -> Frame:
        if p["message"] != cache["message"]:
            cache["message"] = p["message"]
            cache["segments"] = morse_timeline(str(p["message"])[:60]) or [(False, 14)]
            cache["units"] = sum(u for _, u in cache["segments"])
        unit = 1.2 / p["wpm"]
        x = (t / unit) % cache["units"]
        for on, units in cache["segments"]:
            if x < units:
                return paint(p, p["brightness"] if on else p["floor"])
            x -= units
        return paint(p, p["floor"])
    return step


# -- a day in a minute ------------------------------------------------------------------------

_DAY: list[tuple[float, str, float, float, float]] = [
    # (fraction, mode, kelvin-or-hue, sat, brightness)
    (0.00, "hsi", 230, 80, 2), (0.16, "hsi", 250, 60, 4), (0.22, "hsi", 8, 90, 9),
    (0.30, "hsi", 26, 85, 30), (0.40, "cct", 4300, 0, 70), (0.55, "cct", 6200, 0, 100),
    (0.70, "cct", 4800, 0, 85), (0.80, "cct", 2800, 0, 62), (0.87, "hsi", 18, 92, 30),
    (0.92, "hsi", 330, 65, 12), (1.00, "hsi", 230, 80, 2),
]


def _hs(mode: str, a: float, s: float) -> tuple[float, float]:
    return kelvin_to_hs(a) if mode == "cct" else (a, s)


@effect(
    "day", "A Day in a Minute", CAT,
    "A whole day as a time-lapse: moonlit night, dawn, a hard noon, golden hour and dusk, then night again.",
    (num("seconds", "Length of a day", 60, 10, 600, 5, "s"),
     num("scale", "Overall level", 100, 10, 100, 1, "%")),
    accent="#ffc070",
)
def day(rng: random.Random):
    def step(t: float, p: dict[str, Any]) -> Frame:
        f = (t / p["seconds"]) % 1.0
        for (f0, m0, a0, s0, b0), (f1, m1, a1, s1, b1) in itertools.pairwise(_DAY):
            if f0 <= f <= f1:
                g = ease("smooth", (f - f0) / (f1 - f0))
                level = lerp(b0, b1, g) * p["scale"] / 100
                if m0 == m1 == "cct":
                    return cct(lerp(a0, a1, g), level)
                h0, sat0 = _hs(m0, a0, s0)
                h1, sat1 = _hs(m1, a1, s1)
                return hsi(lerp_hue(h0, h1, g), lerp(sat0, sat1, g), level)
        return hsi(230, 80, 2)
    return step


# -- pomodoro ---------------------------------------------------------------------------------


@effect(
    "pomodoro", "Focus Timer", CAT,
    "Cool, bright light while you work, warm and low for the break, with three soft pulses at each change.",
    (num("focus", "Focus", 25, 1, 90, 1, "min"),
     num("rest", "Break", 5, 1, 30, 1, "min"),
     kelvin("work_k", "Focus white", 5200),
     kelvin("rest_k", "Break white", 2700),
     num("work_b", "Focus level", 70, 5, 100, 1, "%"),
     num("rest_b", "Break level", 35, 1, 100, 1, "%")),
    accent="#9fd3ff",
)
def pomodoro(rng: random.Random):
    def step(t: float, p: dict[str, Any]) -> Frame:
        cycle = (p["focus"] + p["rest"]) * 60
        x = t % cycle
        working = x < p["focus"] * 60
        since = x if working else x - p["focus"] * 60
        k, b = (p["work_k"], p["work_b"]) if working else (p["rest_k"], p["rest_b"])
        if since < 3.0:  # three soft pulses announce the switch
            b = b * (0.55 + 0.45 * (0.5 + 0.5 * math.cos(2 * math.pi * since)))
        return cct(k, b)
    return step


# -- breath guide -----------------------------------------------------------------------------

_BREATHS = {"478": (4, 7, 8, 0), "box": (4, 4, 4, 4), "coherent": (5.5, 0, 5.5, 0)}


@effect(
    "breath", "Breath Guide", CAT,
    "Breathe with the light: in as it rises, hold, out as it falls.",
    (choice("pattern", "Pattern", "478", [("478", "4-7-8 relax"), ("box", "Box 4-4-4-4"), ("coherent", "Coherent 5.5")]),
     *source_params("#7fd1ff", 3000),
     num("low", "Out", 5, 0, 60, 1, "%"),
     num("high", "In", 55, 5, 100, 1, "%")),
    accent="#7fd1ff",
)
def breath(rng: random.Random):
    def step(t: float, p: dict[str, Any]) -> Frame:
        inhale, hold, exhale, rest = _BREATHS.get(p["pattern"], _BREATHS["478"])
        x = t % (inhale + hold + exhale + rest)
        if x < inhale:
            f = ease("inout", x / inhale)
        elif x < inhale + hold:
            f = 1.0
        elif x < inhale + hold + exhale:
            f = 1 - ease("inout", (x - inhale - hold) / exhale)
        else:
            f = 0.0
        return paint(p, lerp(p["low"], p["high"], f))
    return step


# -- golden-angle drift -----------------------------------------------------------------------


@effect(
    "golden", "Golden-Angle Drift", CAT,
    "Never repeats: each colour is 137.5 degrees round the wheel from the last, the angle sunflowers use to pack seeds.",
    (num("hold", "Hold", 4, 0.2, 60, 0.1, "s"),
     num("fade", "Glide", 2.5, 0.1, 30, 0.1, "s"),
     num("brightness", "Brightness", 55, 1, 100, 1, "%"),
     num("sat", "Saturation", 90, 20, 100, 1, "%")),
    accent="#ffd166",
)
def golden(rng: random.Random):
    phi = 137.50776405

    def step(t: float, p: dict[str, Any]) -> Frame:
        seg = p["hold"] + p["fade"]
        n = int(t // seg)
        local = t - n * seg
        h0, h1 = (n * phi) % 360, ((n + 1) * phi) % 360
        if local < p["hold"]:
            return hsi(h0, p["sat"], p["brightness"])
        return hsi(lerp_hue(h0, h1, ease("inout", (local - p["hold"]) / p["fade"])), p["sat"], p["brightness"])
    return step


# -- starfield --------------------------------------------------------------------------------


@effect(
    "stars", "Starfield", CAT,
    "A dark night sky where stars catch the light now and then.",
    (num("rate", "Twinkles / minute", 40, 1, 300, 1),
     num("sky", "Sky level", 3, 0, 20, 1, "%"),
     num("sparkle", "Sparkle", 35, 5, 100, 1, "%"),
     num("hue", "Sky hue", 228, 180, 280, 1, "°")),
    accent="#b9c7ff",
)
def stars(rng: random.Random):
    twinkles = Poisson(rng)
    star = {"at": -9.0, "power": 0.0}

    def step(t: float, p: dict[str, Any]) -> Frame:
        if twinkles.due(t, p["rate"]):
            star["at"] = t
            star["power"] = rng.uniform(0.4, 1.0)
        age = t - star["at"]
        glint = star["power"] * math.exp(-age * 7) * min(1.0, age / 0.03) if age >= 0 else 0.0
        level = p["sky"] + p["sparkle"] * glint
        return hsi(p["hue"], lerp(80, 25, glint), level)
    return step


# -- siren with doppler -----------------------------------------------------------------------


@effect(
    "doppler", "Passing Siren", CAT,
    "An emergency vehicle approaching, rushing past and fading into the distance, looped.",
    (num("period", "Pass every", 9, 3, 60, 0.5, "s"),
     num("brightness", "Closest", 90, 10, 100, 1, "%"),
     choice("style", "Colours", "rb", [("rb", "Red and blue"), ("red", "Red"), ("amber", "Amber")])),
    accent="#ff3b6b",
)
def doppler(rng: random.Random):
    phase = {"x": 0.0, "last": None}

    def step(t: float, p: dict[str, Any]) -> Frame:
        f = (t % p["period"]) / p["period"]
        closeness = math.exp(-((f - 0.45) / 0.18) ** 2)
        rate = lerp(2.2, 5.5, closeness) if f < 0.45 else lerp(1.6, 5.5, closeness)  # pitch drops after passing
        last = phase["last"]
        phase["x"] += rate * (t - last if last is not None and t > last else 0.0)
        phase["last"] = t
        on_a = (phase["x"] % 1.0) < 0.5
        hues = {"rb": (0.0, 228.0), "red": (0.0, 0.0), "amber": (32.0, 32.0)}[p["style"]]
        level = p["brightness"] * (0.08 + 0.92 * closeness)
        return hsi(hues[0] if on_a else hues[1], 100, level * (1.0 if on_a or p["style"] == "rb" else 0.15))
    return step


# -- image scan -------------------------------------------------------------------------------


@effect(
    "scan", "Image Scan", CAT,
    "Plays a picture left to right as light: a sunset photo becomes a sunset. Load colours from an image on the Colour tab.",
    (Param("colors", "Colours, left to right", "palette", ("#0b1d3a", "#3a2a6b", "#c2416b", "#ff8a3d", "#ffd27a"), max=64),
     num("seconds", "Length", 30, 2, 600, 1, "s"),
     num("brightness", "Brightness", 60, 1, 100, 1, "%"),
     toggle("bounce", "Play back and forth", True),
     toggle("follow", "Brightness follows the picture", True)),
    accent="#ff8a3d",
)
def scan(rng: random.Random):
    def step(t: float, p: dict[str, Any]) -> Frame:
        colors = p["colors"]
        n = len(colors)
        if n == 1:
            h, s = hex_to_hs(colors[0])
            return hsi(h, s, p["brightness"])
        f = (t / p["seconds"]) % (2.0 if p["bounce"] else 1.0)
        if f > 1.0:
            f = 2.0 - f
        pos = f * (n - 1)
        i = min(n - 2, int(pos))
        g = ease("smooth", pos - i)
        h0, s0 = hex_to_hs(colors[i])
        h1, s1 = hex_to_hs(colors[i + 1])
        level = p["brightness"]
        if p["follow"]:
            v0 = rgb_to_hsv(hex_to_rgb(colors[i]))[2]
            v1 = rgb_to_hsv(hex_to_rgb(colors[i + 1]))[2]
            level *= clamp(lerp(v0, v1, g) / 100, 0.08, 1.0)
        return hsi(lerp_hue(h0, h1, g), lerp(s0, s1, g), level)
    return step

