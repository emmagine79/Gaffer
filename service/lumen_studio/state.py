"""The light's state as the studio models it.

Commands to the light are fire-and-forget and its readback only covers the
colour-temperature mode, so this model -- not the light -- is the source of
truth. Every mode keeps its own settings, so switching from colour back to white
returns to the white you had.

All models are frozen; :func:`apply_patch` returns a new state.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .catalog import ModelCaps

Mode = Literal["cct", "hsi", "rgbw", "gel", "fx"]
MODES: tuple[str, ...] = ("cct", "hsi", "rgbw", "gel", "fx")


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Cct(_Frozen):
    kelvin: int = 5600
    gm: int = 0


class Hsi(_Frozen):
    hue: float = Field(default=20.0, ge=0, le=360)
    sat: float = Field(default=100.0, ge=0, le=100)


class Rgbw(_Frozen):
    r: int = Field(default=1000, ge=0, le=1000)
    g: int = Field(default=300, ge=0, le=1000)
    b: int = Field(default=0, ge=0, le=1000)
    w: int = Field(default=0, ge=0, le=1000)


class Gel(_Frozen):
    version: int
    brand: int
    number: int
    sub_brand: int = 0
    label: str = ""
    hex: str = "#808080"


class Fx(_Frozen):
    symbol: int
    speed: int | None = Field(default=None, ge=0, le=100)
    params: dict[str, int] = Field(default_factory=dict)


class LightState(_Frozen):
    power: bool = True
    brightness: float = Field(default=50.0, ge=0, le=100)
    mode: Mode = "cct"
    cct: Cct = Cct()
    hsi: Hsi = Hsi()
    rgbw: Rgbw = Rgbw()
    gel: Gel | None = None
    fx: Fx | None = None


class StateError(ValueError):
    """A requested state the light cannot take."""


def _merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict) and key != "params":
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def merge_patch(state: LightState, patch: dict[str, Any]) -> dict[str, Any]:
    """``state`` as a plain dict with ``patch`` deep-merged in; not yet validated."""
    return _merge(state.model_dump(), patch)


def apply_patch(state: LightState, patch: dict[str, Any], caps: ModelCaps) -> LightState:
    """Return ``state`` with ``patch`` deep-merged in, validated against ``caps``.

    Raises
    ------
    StateError
        When the result is outside what this model accepts.
    """
    try:
        candidate = LightState.model_validate(_merge(state.model_dump(), patch))
    except ValueError as err:
        raise StateError(str(err)) from err
    validate(candidate, caps)
    return candidate


def validate(state: LightState, caps: ModelCaps) -> None:
    """Raise :class:`StateError` if ``state`` asks for something ``caps`` rules out."""
    if caps.has_white and not caps.min_kelvin <= state.cct.kelvin <= caps.max_kelvin:
        raise StateError(
            f"{caps.name} takes {caps.min_kelvin}-{caps.max_kelvin} K, not {state.cct.kelvin} K"
        )
    if not caps.gm_min <= state.cct.gm <= caps.gm_max:
        raise StateError(f"tint must be {caps.gm_min}..{caps.gm_max}, not {state.cct.gm}")
    if state.mode == "cct" and not caps.has_white:
        raise StateError(f"{caps.name} has no white mode")
    if state.mode == "hsi" and not caps.has_colour:
        raise StateError(f"{caps.name} has no colour mode")
    if state.mode == "rgbw" and not caps.has_channels:
        raise StateError(f"{caps.name} has no direct channel mode")
    if state.mode == "gel":
        if state.gel is None:
            raise StateError("gel mode needs a gel")
        if caps.gel_support is None:
            raise StateError(f"{caps.name} cannot show gels")
    if state.mode == "fx":
        if state.fx is None:
            raise StateError("effect mode needs an effect")
        effect = next((e for e in caps.effects if e.symbol == state.fx.symbol), None)
        if effect is None:
            raise StateError(f"{caps.name} has no effect symbol {state.fx.symbol}")
        unknown = set(state.fx.params) - {p["key"] for p in effect.params}
        if unknown:
            raise StateError(f"effect {state.fx.symbol} has no parameter(s) {sorted(unknown)}")
        if state.fx.speed is not None and state.fx.speed > effect.speed_max:
            raise StateError(f"{effect.name} runs at speed 0-{effect.speed_max}, not {state.fx.speed}")
