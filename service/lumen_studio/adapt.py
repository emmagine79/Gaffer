"""Fitting any look onto the light that is actually connected. Pure.

Effects, music and screen sync, timelines and saved scenes all speak in full
colour. Most of the Godox range cannot: half the catalogue is white only, some
of it at a single fixed temperature, and one model is colour without white.
Rather than hide those features, every frame and state passes through here and
comes out as the nearest thing the light can show:

* colour on a white-only light becomes the matching warmth, with green and
  magenta on the tint axis when the light has one (red glows warm, blue cool);
* white on a colour-only light becomes the hue of that temperature;
* direct channels on a light without them become hue and saturation;
* a daylight light keeps the brightness, which is all it has.

Brightness and power always pass through unchanged.
"""

from __future__ import annotations

from typing import Any

from .catalog import ModelCaps
from .colormath import clamp, hsv_to_rgb, kelvin_to_rgb, rgb_to_hsv
from .effects.base import Frame
from .gel_emulation import emulate, fits_white_light, white_for
from .state import Cct, Fx, Hsi, LightState, StateError, validate


def _white_frame(rgb: tuple[float, float, float], brightness: float, caps: ModelCaps) -> Frame:
    white = white_for(rgb, caps)
    return Frame("cct", brightness, kelvin=white["kelvin"], gm=white["gm"])


def _channels_hs(rgbw: tuple[int, int, int, int]) -> tuple[float, float]:
    r, g, b, w = (max(0, v) for v in rgbw)
    peak = max(r + w, g + w, b + w, 1)
    hue, sat, _ = rgb_to_hsv(((r + w) / peak, (g + w) / peak, (b + w) / peak))
    return hue, sat


def adapt_frame(frame: Frame, caps: ModelCaps) -> Frame:
    """The frame as this light can show it. Returned as-is when it already fits."""
    if frame.mode == "hsi":
        if caps.has_colour or not caps.has_white:
            return frame
        return _white_frame(hsv_to_rgb(frame.hue, frame.sat), frame.brightness, caps)
    if frame.mode == "rgbw":
        if caps.has_channels:
            return frame
        hue, sat = _channels_hs(frame.rgbw)
        return adapt_frame(Frame("hsi", frame.brightness, hue=hue, sat=sat), caps)
    if caps.has_white:
        kelvin = int(clamp(frame.kelvin, caps.min_kelvin, caps.max_kelvin))
        gm = int(clamp(frame.gm, caps.gm_min, caps.gm_max))
        if (kelvin, gm) == (frame.kelvin, frame.gm):
            return frame
        return Frame("cct", frame.brightness, kelvin=kelvin, gm=gm)
    if caps.has_colour:
        hue, sat, _ = rgb_to_hsv(kelvin_to_rgb(frame.kelvin))
        return Frame("hsi", frame.brightness, hue=hue, sat=sat)
    return frame


def _look(frame: Frame) -> dict[str, Any]:
    """A state patch for a cct or hsi frame."""
    if frame.mode == "cct":
        return {"mode": "cct", "cct": Cct(kelvin=frame.kelvin, gm=frame.gm)}
    return {"mode": "hsi", "hsi": Hsi(hue=round(frame.hue, 1) % 360, sat=round(clamp(frame.sat, 0, 100), 1))}


def _current_frame(state: LightState) -> Frame:
    if state.mode == "hsi":
        return Frame("hsi", state.brightness, hue=state.hsi.hue, sat=state.hsi.sat)
    if state.mode == "rgbw":
        c = state.rgbw
        return Frame("rgbw", state.brightness, rgbw=(c.r, c.g, c.b, c.w))
    return Frame("cct", state.brightness, kelvin=state.cct.kelvin, gm=state.cct.gm)


def _gel_update(state: LightState, caps: ModelCaps) -> dict[str, Any]:
    """Keep a gel the light can show as a gel; otherwise turn it into its look."""
    gel = state.gel
    if gel is None:
        return _look(adapt_frame(_current_frame(state.model_copy(update={"mode": "cct"})), caps))
    support = caps.gel_support
    if (
        (support == "native" and gel.version == caps.color_chip_version)
        or support == "emulated"
        or (support == "white" and fits_white_light(gel.hex, caps))
    ):
        return {}
    look = emulate(gel.hex, caps)
    if look["mode"] == "cct":
        return {"mode": "cct", "cct": Cct(kelvin=look["kelvin"], gm=look["gm"])}
    return {"mode": "hsi", "hsi": Hsi(hue=look["hue"], sat=look["sat"])}


def _fx_update(state: LightState, caps: ModelCaps) -> dict[str, Any]:
    fx = state.fx
    effect = next((e for e in caps.effects if fx is not None and e.symbol == fx.symbol), None)
    if fx is None or effect is None:
        fallback = "cct" if caps.has_white else "hsi"
        return {"mode": fallback}
    allowed = {p["key"] for p in effect.params}
    params = {k: v for k, v in fx.params.items() if k in allowed}
    speed = None if fx.speed is None else int(clamp(fx.speed, 0, effect.speed_max))
    if params == fx.params and speed == fx.speed:
        return {}
    return {"fx": Fx(symbol=fx.symbol, speed=speed, params=params)}


def adapt_state(state: LightState, caps: ModelCaps) -> LightState:
    """``state`` as this light can take it: same power and brightness, nearest look.

    Total for every controllable model: the result always passes
    :func:`lumen_studio.state.validate`. A model the studio cannot drive at
    all is returned the state unchanged.
    """
    if caps.kind == "unsupported":
        return state
    update: dict[str, Any] = {}
    kelvin = int(clamp(state.cct.kelvin, caps.min_kelvin, caps.max_kelvin)) if caps.has_white else state.cct.kelvin
    gm = int(clamp(state.cct.gm, caps.gm_min, caps.gm_max))
    if (kelvin, gm) != (state.cct.kelvin, state.cct.gm):
        update["cct"] = Cct(kelvin=kelvin, gm=gm)
    clamped = state.model_copy(update=update)

    if state.mode == "gel":
        update.update(_gel_update(clamped, caps))
    elif state.mode == "fx":
        update.update(_fx_update(clamped, caps))
        if update.get("mode") == "cct" and not caps.has_white:
            update["mode"] = "hsi"
    else:
        frame = _current_frame(clamped)
        fitted = adapt_frame(frame, caps)
        if fitted is not frame:
            update.update(_look(fitted))
    adapted = state.model_copy(update=update)
    try:
        validate(adapted, caps)
    except StateError:
        # Defensive: a look that still does not fit falls back to plain white or colour.
        adapted = state.model_copy(update={**update, "mode": "cct" if caps.has_white else "hsi"})
    return adapted
