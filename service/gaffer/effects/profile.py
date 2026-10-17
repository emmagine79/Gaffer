"""What each software effect actually does, found by running it. Pure.

An effect declares its parameters, not its behaviour. The studio needs two
facts about each one to present it honestly on a given light: whether it uses
colour (on a white-only light it plays as warmth instead) and whether its
brightness moves (on a fixed-daylight light that is all that is left of it).
Both are measured by sampling two minutes of the effect at its defaults.
"""

from __future__ import annotations

import random
from functools import cache

from .base import REGISTRY

SAMPLE_SECONDS = 120.0
SAMPLE_STEP = 0.25
#: Brightness swing, in percentage points, that counts as movement.
MOTION_THRESHOLD = 3.0
#: Saturation below this is a tinted white, not colour.
COLOUR_THRESHOLD = 12.0


@cache
def effect_profile(effect_id: str) -> dict[str, bool]:
    effect = REGISTRY[effect_id]
    step = effect.factory(random.Random(11))
    params = effect.resolve(None)
    colour = False
    low, high = 100.0, 0.0
    t = 0.0
    while t <= SAMPLE_SECONDS:
        frame = step(t, params)
        if (frame.mode == "hsi" and frame.sat >= COLOUR_THRESHOLD) or frame.mode == "rgbw":
            colour = True
        low, high = min(low, frame.brightness), max(high, frame.brightness)
        t += SAMPLE_STEP
    return {"colour": colour, "brightness_moves": high - low >= MOTION_THRESHOLD}
