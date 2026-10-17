"""The contract every software effect follows.

An effect is a factory: given a seeded random generator it returns a ``step``
function, ``step(t, params) -> Frame``, where ``t`` is seconds since start.
Effects are pure apart from the state their factory closes over, so a test can
sweep any of them across time with a fixed seed.

Parameters are declared as data (:class:`Param`). The UI renders controls from
the declaration, so a new effect needs no UI code at all.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

FrameMode = Literal["cct", "hsi", "rgbw"]


@dataclass(frozen=True, slots=True)
class Frame:
    mode: FrameMode
    brightness: float
    kelvin: int = 5600
    gm: int = 0
    hue: float = 0.0
    sat: float = 100.0
    rgbw: tuple[int, int, int, int] = (0, 0, 0, 0)


def hsi(hue: float, sat: float, brightness: float) -> Frame:
    return Frame("hsi", max(0.0, min(100.0, brightness)), hue=hue % 360.0, sat=max(0.0, min(100.0, sat)))


def cct(kelvin: float, brightness: float, gm: int = 0) -> Frame:
    return Frame("cct", max(0.0, min(100.0, brightness)), kelvin=int(round(kelvin / 50.0) * 50), gm=gm)


ParamKind = Literal["number", "color", "kelvin", "palette", "choice", "bool", "text"]


@dataclass(frozen=True, slots=True)
class Param:
    key: str
    label: str
    kind: ParamKind
    default: Any
    min: float | None = None
    max: float | None = None
    step: float | None = None
    unit: str = ""
    options: tuple[dict[str, Any], ...] = ()
    hint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v not in (None, "", ())}


def num(key: str, label: str, default: float, lo: float, hi: float, step: float = 1, unit: str = "", hint: str = "") -> Param:
    return Param(key, label, "number", default, lo, hi, step, unit, hint=hint)


def color(key: str, label: str, default: str) -> Param:
    return Param(key, label, "color", default)


def kelvin(key: str, label: str, default: int) -> Param:
    return Param(key, label, "kelvin", default, 1800, 10000, 50, "K")


def palette(key: str, label: str, default: list[str]) -> Param:
    return Param(key, label, "palette", tuple(default))


def choice(key: str, label: str, default: str, options: list[tuple[str, str]]) -> Param:
    return Param(key, label, "choice", default, options=tuple({"value": v, "label": lab} for v, lab in options))


def toggle(key: str, label: str, default: bool) -> Param:
    return Param(key, label, "bool", default)


Step = Callable[[float, dict[str, Any]], Frame]
Factory = Callable[[random.Random], Step]


@dataclass(frozen=True, slots=True)
class Effect:
    id: str
    name: str
    category: str
    description: str
    params: tuple[Param, ...]
    factory: Factory = field(repr=False)
    accent: str = "#ffb347"
    trigger: str = ""  # label for a manual-trigger button, empty when there is none

    def defaults(self) -> dict[str, Any]:
        return {p.key: (list(p.default) if p.kind == "palette" else p.default) for p in self.params}

    def resolve(self, params: dict[str, Any] | None) -> dict[str, Any]:
        """Defaults overlaid with ``params``, numbers clamped to their ranges."""
        merged = self.defaults()
        for p in self.params:
            if params is None or p.key not in params:
                continue
            value = params[p.key]
            if p.kind == "number":
                value = float(value)
                if p.min is not None:
                    value = max(p.min, value)
                if p.max is not None:
                    value = min(p.max, value)
            elif p.kind == "kelvin":
                value = int(max(1800, min(10000, float(value))))
            elif p.kind == "bool":
                value = bool(value)
            elif p.kind == "color":
                value = str(value) if _is_hex(value) else merged[p.key]
            elif p.kind == "palette":
                value = [str(c) for c in value if _is_hex(c)][: int(p.max or 12)] or merged[p.key]
            elif p.kind == "text":
                value = str(value)[:80]
            merged[p.key] = value
        return merged

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "accent": self.accent,
            "trigger": self.trigger,
            "params": [p.to_dict() for p in self.params],
        }


def _is_hex(value: Any) -> bool:
    text = str(value).lstrip("#")
    return len(text) in (3, 6) and all(c in "0123456789abcdefABCDEF" for c in text)


REGISTRY: dict[str, Effect] = {}


def effect(
    id: str,
    name: str,
    category: str,
    description: str,
    params: tuple[Param, ...] = (),
    accent: str = "#ffb347",
    trigger: str = "",
) -> Callable[[Factory], Factory]:
    def register(factory: Factory) -> Factory:
        if id in REGISTRY:
            raise ValueError(f"duplicate effect id {id!r}")
        REGISTRY[id] = Effect(id, name, category, description, params, factory, accent, trigger)
        return factory

    return register
