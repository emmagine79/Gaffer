"""Moving several lights with one fader, keeping their levels relative to each other.

Pure arithmetic, no light and no clock, so the rule is the same for every client.
Levels are brightness percentages, 0 to 100.
"""

from __future__ import annotations

import math

LOW, HIGH = 0.0, 100.0


def _clamp(level: float) -> float:
    return min(HIGH, max(LOW, level))


def scale_levels(
    levels: dict[str, float], anchor: str, new_level: float, start: dict[str, float] | None = None,
) -> dict[str, float]:
    """The new level of every light when ``anchor`` is dragged to ``new_level``.

    Every other light keeps its ratio to the anchor (40, 25, 60 with the first dragged
    to 80 gives 80, 50, 100). An anchor at 0 has no ratio, so the others take the same
    absolute step instead. Every level is held between 0 and 100.

    ``start`` is every light's level when the drag began. With it the rule is applied to
    those levels for the whole drag, so dragging the anchor to 0 or past a limit and back
    gives the original balance again. Without it the rule starts from ``levels``.
    Raises ``KeyError`` for an anchor that is not in ``levels`` and ``ValueError`` for
    a level that is not a finite number.
    """
    if isinstance(new_level, bool) or not isinstance(new_level, (int, float)) or not math.isfinite(new_level):
        raise ValueError("the level must be a number")
    origin = levels if start is None else {light_id: start[light_id] for light_id in levels}
    old = origin[anchor]
    target = _clamp(float(new_level))
    out: dict[str, float] = {}
    for light_id, level in origin.items():
        if light_id == anchor:
            out[light_id] = target
        elif old > 0:
            out[light_id] = _clamp(level * target / old)
        else:
            out[light_id] = _clamp(level + (target - old))
    return out
