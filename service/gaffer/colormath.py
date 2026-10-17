"""Colour conversions shared by effects, transitions and previews. Pure."""

from __future__ import annotations

import math


def clamp(value: float, low: float, high: float) -> float:
    return low if value < low else min(value, high)


def lerp(a: float, b: float, f: float) -> float:
    return a + (b - a) * f


def lerp_hue(a: float, b: float, f: float) -> float:
    """Interpolate hue the short way round the wheel."""
    delta = ((b - a + 540.0) % 360.0) - 180.0
    return (a + delta * f) % 360.0


def hex_to_rgb(value: str) -> tuple[float, float, float]:
    text = value.lstrip("#")
    if len(text) == 3:
        text = "".join(c * 2 for c in text)
    if len(text) != 6:
        raise ValueError(f"not a hex colour: {value!r}")
    return tuple(int(text[i : i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]


def rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{round(clamp(c, 0, 1) * 255):02x}" for c in rgb)


def rgb_to_hsv(rgb: tuple[float, float, float]) -> tuple[float, float, float]:
    """Return hue 0-360, saturation 0-100, value 0-100."""
    r, g, b = rgb
    high, low = max(rgb), min(rgb)
    span = high - low
    if span == 0:
        hue = 0.0
    elif high == r:
        hue = 60.0 * (((g - b) / span) % 6)
    elif high == g:
        hue = 60.0 * ((b - r) / span + 2)
    else:
        hue = 60.0 * ((r - g) / span + 4)
    sat = 0.0 if high == 0 else span / high
    return hue % 360.0, sat * 100.0, high * 100.0


def hsv_to_rgb(hue: float, sat: float, val: float = 100.0) -> tuple[float, float, float]:
    h = (hue % 360.0) / 60.0
    s, v = sat / 100.0, val / 100.0
    c = v * s
    x = c * (1 - abs(h % 2 - 1))
    m = v - c
    r, g, b = [(c, x, 0), (x, c, 0), (0, c, x), (0, x, c), (x, 0, c), (c, 0, x)][int(h) % 6]
    return r + m, g + m, b + m


def hex_to_hs(value: str) -> tuple[float, float]:
    hue, sat, _ = rgb_to_hsv(hex_to_rgb(value))
    return hue, sat


def kelvin_to_rgb(kelvin: float) -> tuple[float, float, float]:
    """Approximate blackbody colour (Tanner Helland's fit), 0-1 per channel."""
    t = clamp(kelvin, 1000, 40000) / 100.0
    if t <= 66:
        r = 255.0
        g = 99.4708025861 * math.log(t) - 161.1195681661
        b = 0.0 if t <= 19 else 138.5177312231 * math.log(t - 10) - 305.0447927307
    else:
        r = 329.698727446 * (t - 60) ** -0.1332047592
        g = 288.1221695283 * (t - 60) ** -0.0755148492
        b = 255.0
    return tuple(clamp(c, 0, 255) / 255.0 for c in (r, g, b))  # type: ignore[return-value]


def kelvin_to_hs(kelvin: float) -> tuple[float, float]:
    hue, sat, _ = rgb_to_hsv(kelvin_to_rgb(kelvin))
    return hue, sat


# -- easing ----------------------------------------------------------------------

def ease(name: str, f: float) -> float:
    f = clamp(f, 0.0, 1.0)
    if name == "linear":
        return f
    if name == "in":
        return f * f * f
    if name == "out":
        return 1 - (1 - f) ** 3
    if name == "step":
        return 0.0 if f < 1 else 1.0
    if name == "smooth":
        return f * f * (3 - 2 * f)
    # "inout" and anything unknown
    return 4 * f**3 if f < 0.5 else 1 - (-2 * f + 2) ** 3 / 2


EASINGS: tuple[str, ...] = ("linear", "inout", "in", "out", "smooth", "step")


# -- noise -------------------------------------------------------------------------

class ValueNoise:
    """Smooth 1-D value noise: organic flicker without a dependency."""

    def __init__(self, rng_values: list[float]) -> None:
        self._v = rng_values
        self._n = len(rng_values)

    def __call__(self, x: float) -> float:
        i = math.floor(x)
        f = x - i
        a = self._v[i % self._n]
        b = self._v[(i + 1) % self._n]
        f = f * f * (3 - 2 * f)
        return a + (b - a) * f

    def fbm(self, x: float, octaves: int = 3) -> float:
        total, amp, freq, norm = 0.0, 1.0, 1.0, 0.0
        for _ in range(octaves):
            total += self(x * freq + 17.3 * freq) * amp
            norm += amp
            amp *= 0.5
            freq *= 2.0
        return total / norm
