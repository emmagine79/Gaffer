"""Practical-light effects for film and photo sets."""

from __future__ import annotations

import math
import random
from typing import Any

from ..colormath import hex_to_hs
from .base import Frame, cct, choice, color, effect, hsi, kelvin, num, palette
from .common import Poisson, Trigger, noise

CAT = "Cinematic"

_POLICE: dict[str, list[tuple[str | None, float]]] = {
    # (colour, seconds at speed 1); None is dark
    "us": [("#ff0000", .07), (None, .05), ("#ff0000", .07), (None, .05), ("#ff0000", .07), (None, .12),
           ("#0033ff", .07), (None, .05), ("#0033ff", .07), (None, .05), ("#0033ff", .07), (None, .12)],
    "eu": [("#0030ff", .06), (None, .06), ("#0030ff", .06), (None, .35)],
    "amber": [("#ff8c00", .09), (None, .09), ("#ff8c00", .09), (None, .3)],
    "fire": [("#ff0000", .12), ("#ffffff", .06), ("#ff0000", .12), (None, .2)],
}


@effect(
    "police", "Emergency Lights", CAT,
    "Strobe patterns from US and EU emergency vehicles, utility amber and fire engines.",
    (choice("style", "Pattern", "us", [("us", "US police"), ("eu", "EU police"), ("amber", "Amber beacon"), ("fire", "Fire engine")]),
     num("speed", "Speed", 1.0, 0.3, 2.5, 0.05, "x"),
     num("brightness", "Brightness", 100, 1, 100, 1, "%")),
    accent="#2f6bff",
)
def police(rng: random.Random):
    def step(t: float, p: dict[str, Any]) -> Frame:
        pattern = _POLICE[p["style"]]
        total = sum(d for _, d in pattern) / p["speed"]
        x = t % total
        for hexcol, length in pattern:
            length /= p["speed"]
            if x < length:
                if hexcol is None:
                    return hsi(0, 100, 0)
                if hexcol == "#ffffff":
                    return cct(6500, p["brightness"])
                hue, sat = hex_to_hs(hexcol)
                return hsi(hue, sat, p["brightness"])
            x -= length
        return hsi(0, 100, 0)
    return step


@effect(
    "paparazzi", "Paparazzi", CAT,
    "Camera flashes going off at random across a dim room. Fire one on cue with the trigger.",
    (num("rate", "Flashes / minute", 90, 0, 400, 1),
     num("intensity", "Flash power", 100, 10, 100, 1, "%"),
     kelvin("kelvin", "Flash colour", 5600),
     num("ambient", "Room level", 5, 0, 40, 1, "%")),
    accent="#ffffff",
    trigger="Flash",
)
def paparazzi(rng: random.Random):
    flashes = Poisson(rng)
    cue = Trigger()
    state = {"until": -1.0}

    def step(t: float, p: dict[str, Any]) -> Frame:
        if flashes.due(t, p["rate"]) or cue.fired(p):
            state["until"] = t + rng.uniform(0.03, 0.07)
        if t <= state["until"]:
            return cct(p["kelvin"], p["intensity"])
        return cct(3200, p["ambient"])
    return step


@effect(
    "neon", "Failing Neon", CAT,
    "A neon sign that hums along steadily, then stutters and drops out.",
    (color("color", "Tube colour", "#ff2bd6"),
     num("brightness", "Brightness", 80, 1, 100, 1, "%"),
     num("stability", "Stability", 70, 0, 100, 1, hint="Lower fails more often")),
    accent="#ff2bd6",
)
def neon(rng: random.Random):
    bursts = Poisson(rng)
    hum = noise(rng)
    state = {"until": -1.0}

    def step(t: float, p: dict[str, Any]) -> Frame:
        if bursts.due(t, (100 - p["stability"]) / 2.5 + 0.5):
            state["until"] = t + rng.uniform(0.2, 1.4)
        hue, sat = hex_to_hs(p["color"])
        if t < state["until"]:
            on = rng.random() > 0.45
            return hsi(hue, sat, p["brightness"] * (rng.uniform(0.5, 1.0) if on else rng.uniform(0, 0.08)))
        return hsi(hue, sat, p["brightness"] * (0.94 + 0.06 * hum(t * 20)))
    return step


@effect(
    "tv", "TV Glow", CAT,
    "Someone watching TV in the dark: cool shifting light with sudden scene cuts.",
    (num("brightness", "Brightness", 40, 1, 100, 1, "%"),
     num("cuts", "Cuts / minute", 18, 1, 80, 1),
     num("colorful", "Colourfulness", 35, 0, 100, 1)),
    accent="#6ea8ff",
)
def tv(rng: random.Random):
    cuts = Poisson(rng)
    flick = noise(rng)
    scene = {"hue": 215.0, "sat": 30.0, "level": 0.8}

    def step(t: float, p: dict[str, Any]) -> Frame:
        if cuts.due(t, p["cuts"]):
            c = p["colorful"] / 100.0
            scene["hue"] = (210 + rng.gauss(0, 20 + 120 * c)) % 360
            scene["sat"] = rng.uniform(5, 25 + 60 * c)
            scene["level"] = rng.uniform(0.35, 1.0)
        level = p["brightness"] * scene["level"] * (0.82 + 0.18 * flick.fbm(t * 4))
        return hsi(scene["hue"], scene["sat"], level)
    return step


@effect(
    "projector", "Film Projector", CAT,
    "The warm flutter of an old film projector, frame by frame, with the odd splice.",
    (num("fps", "Frame rate", 18, 8, 24, 1, "fps"),
     kelvin("kelvin", "Lamp", 3200),
     num("brightness", "Brightness", 70, 1, 100, 1, "%"),
     num("flicker", "Flutter", 50, 0, 100, 1)),
    accent="#ffd59e",
)
def projector(rng: random.Random):
    splices = Poisson(rng)
    state = {"frame": -1, "level": 1.0, "dip_until": -1.0}

    def step(t: float, p: dict[str, Any]) -> Frame:
        frame = int(t * p["fps"])
        if frame != state["frame"]:
            state["frame"] = frame
            state["level"] = 1.0 - rng.random() * 0.3 * p["flicker"] / 100.0
        if splices.due(t, 3 * p["flicker"] / 100.0):
            state["dip_until"] = t + 0.08
        level = p["brightness"] * state["level"] * (0.35 if t < state["dip_until"] else 1.0)
        return cct(p["kelvin"], level)
    return step


@effect(
    "horror", "Haunted", CAT,
    "A cold, sickly light that breathes unevenly and cuts out when you least expect it.",
    (color("color", "Tint", "#9dff9a"),
     num("brightness", "Brightness", 35, 1, 100, 1, "%"),
     num("dread", "Dread", 50, 0, 100, 1)),
    accent="#9dff9a",
)
def horror(rng: random.Random):
    drops = Poisson(rng)
    n = noise(rng)
    state = {"until": -1.0}

    def step(t: float, p: dict[str, Any]) -> Frame:
        if drops.due(t, 2 + 10 * p["dread"] / 100.0):
            state["until"] = t + rng.uniform(0.1, 1.6)
        hue, sat = hex_to_hs(p["color"])
        if t < state["until"]:
            return hsi(hue, sat, p["brightness"] * (0.25 * rng.random() if rng.random() < 0.3 else 0.0))
        return hsi(hue, sat * 0.6, p["brightness"] * (0.6 + 0.4 * n.fbm(t * 0.7)))
    return step


@effect(
    "beacon", "Rotating Beacon", CAT,
    "A spinning warning light sweeping past the lens.",
    (color("color", "Colour", "#ff9500"),
     num("rpm", "Rotation", 70, 10, 240, 1, "rpm"),
     num("brightness", "Brightness", 100, 1, 100, 1, "%"),
     num("sharpness", "Beam width", 6, 1, 20, 1, hint="Higher is a narrower beam")),
    accent="#ff9500",
)
def beacon(rng: random.Random):
    def step(t: float, p: dict[str, Any]) -> Frame:
        phase = 2 * math.pi * t * p["rpm"] / 60.0
        beam = max(0.0, math.cos(phase)) ** p["sharpness"]
        hue, sat = hex_to_hs(p["color"])
        return hsi(hue, sat, p["brightness"] * (0.04 + 0.96 * beam))
    return step


@effect(
    "fireworks", "Fireworks", CAT,
    "Bursts of colour that bloom and crackle away into the dark.",
    (palette("colors", "Shells", ["#ff2d55", "#ffd60a", "#30d158", "#0a84ff", "#bf5af2", "#ffffff"]),
     num("rate", "Bursts / minute", 30, 1, 120, 1),
     num("brightness", "Brightness", 100, 1, 100, 1, "%")),
    accent="#ffd60a",
    trigger="Launch",
)
def fireworks(rng: random.Random):
    bursts = Poisson(rng)
    cue = Trigger()
    shell = {"at": -9.0, "hue": 0.0, "sat": 0.0}

    def step(t: float, p: dict[str, Any]) -> Frame:
        if bursts.due(t, p["rate"]) or cue.fired(p):
            shell["at"] = t
            shell["hue"], shell["sat"] = hex_to_hs(rng.choice(p["colors"]))
        age = t - shell["at"]
        if age < 0 or age > 2.5:
            return hsi(shell["hue"], shell["sat"], 0)
        bloom = min(1.0, age / 0.08) * math.exp(-age * 1.8)
        crackle = 1.0 if age < 0.6 else (0.4 + 0.6 * (rng.random() > 0.5))
        return hsi(shell["hue"], shell["sat"], p["brightness"] * bloom * crackle)
    return step
