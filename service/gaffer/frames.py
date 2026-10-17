"""State to wire bytes. Pure: no I/O, no clock.

Every frame is built by the library's own protocol builders, so the bytes match
what the integration and the vendor app send. Returning bytes rather than
controller calls lets the pump drop a frame identical to the last one sent.
"""

from __future__ import annotations

from godox_mesh_bt.protocol import (
    RGB_TYPE_RGBW,
    SUB_POWER,
    build_cct_command,
    build_color_chip_command,
    build_fx_command,
    build_hsi_command,
    build_rgb_wide_command,
    build_rgbw_command,
    build_v2_command,
)

from .catalog import ModelCaps
from .gel_emulation import emulate
from .state import LightState

POWER_ON = build_v2_command(SUB_POWER, 0xFF, bytes([0x00]))
POWER_OFF = build_v2_command(SUB_POWER, 0xFF, bytes([0x01]))

RGB8_MAX = 255
RGB16_MAX = 1000


def power_frame(on: bool) -> bytes:
    return POWER_ON if on else POWER_OFF


def mode_frame(state: LightState, caps: ModelCaps) -> bytes:
    """The single frame that puts the light into ``state``'s mode and level."""
    level = round(state.brightness, 1)
    if state.mode == "cct":
        return build_cct_command(
            level,
            state.cct.kelvin,
            gm=state.cct.gm,
            supports_gm=caps.has_tint,
            min_kelvin=caps.min_kelvin,
            max_kelvin=caps.max_kelvin,
        )
    if state.mode == "hsi":
        return build_hsi_command(level, round(state.hsi.hue) % 360, round(state.hsi.sat))
    if state.mode == "rgbw":
        c = state.rgbw
        if caps.rgb_display != 0:
            return build_rgb_wide_command(
                level, c.r, c.g, c.b, rgb_type=RGB_TYPE_RGBW, extra=(c.w, 0, 0)
            )
        scale = RGB8_MAX / RGB16_MAX
        return build_rgbw_command(
            level, *(round(v * scale) for v in (c.r, c.g, c.b, c.w))
        )
    if state.mode == "gel":
        gel = state.gel
        assert gel is not None  # guaranteed by state.validate
        if caps.gel_support != "native" or gel.version != caps.color_chip_version:
            # No gel mode in this model's catalogue (the ML100R, every white-only
            # light): it acknowledges gel frames and ignores them, so recreate
            # the gel from its colour.
            look = emulate(gel.hex, caps)
            if look["mode"] == "cct":
                return build_cct_command(
                    level, look["kelvin"], gm=look["gm"], supports_gm=caps.has_tint,
                    min_kelvin=caps.min_kelvin, max_kelvin=caps.max_kelvin,
                )
            return build_hsi_command(level, look["hue"], look["sat"])
        return build_color_chip_command(
            level,
            brand=gel.brand,
            number=gel.number,
            version=gel.version,
            sub_brand=gel.sub_brand,
        )
    fx = state.fx
    assert fx is not None  # guaranteed by state.validate
    # Newer-generation effects list "speed" among their own parameters (that is
    # how the UI sends it); older ones carry it only as fx.speed. Either way it
    # must reach the builder once, as its speed argument.
    params = dict(fx.params)
    speed = params.pop("speed", fx.speed)
    return build_fx_command(
        fx.symbol,
        level,
        speed=speed,
        effect_version=caps.effect_version,
        **params,
    )


def frames_for(state: LightState, caps: ModelCaps) -> tuple[bytes, ...]:
    """Frames that take a light from anything to ``state``."""
    if not state.power:
        return (POWER_OFF,)
    return (POWER_ON, mode_frame(state, caps))
