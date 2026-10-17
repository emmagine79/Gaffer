"""Gels on lights whose catalogue has no gel mode (the ML100R): recreated from colour.

Godox's catalogue lists the ML100R's Bluetooth modes as cct, hsi, rgb and
effects -- no colour-chip mode. It acknowledges gel frames and ignores them
(seen on hardware 2026-10-03), so the studio recreates each gel from its
measured colour instead.
"""

from __future__ import annotations

import pytest
from godox_mesh_bt.protocol import SUB_COLOR_CHIP_EX, SUB_HSI, SUB_SET_CCT

from lumen_studio.catalog import gels, model_caps
from lumen_studio.frames import mode_frame
from lumen_studio.gel_emulation import emulate
from lumen_studio.state import LightState, apply_patch


@pytest.fixture(scope="module")
def caps():
    return model_caps("008F")


def test_the_ml100r_has_no_native_gel_mode(caps):
    assert "color_chip" not in caps.modes


def test_an_orange_correction_gel_becomes_warm_white(caps):
    look = emulate("#ffb464", caps)  # L-GEL COR. 286, a half CTO
    assert look["mode"] == "cct"
    assert 2000 <= look["kelvin"] <= 4200


def test_a_blue_correction_gel_becomes_cool_white(caps):
    look = emulate("#afd9f5", caps)  # L-GEL COR. 283, a CTB
    assert look["mode"] == "cct"
    assert look["kelvin"] >= 7000


def test_a_green_correction_gel_becomes_white_with_green_tint(caps):
    look = emulate("#d4f5c8", caps)  # a plus-green
    assert look["mode"] == "cct"
    assert look["gm"] < -10


def test_a_magenta_correction_gel_tints_the_other_way(caps):
    look = emulate("#f5cde6", caps)  # a minus-green
    assert look["mode"] == "cct"
    assert look["gm"] > 10


def test_a_saturated_gel_becomes_that_colour(caps):
    look = emulate("#4100d4", caps)  # R-GEL SPC. 2008, a deep violet
    assert look["mode"] == "hsi"
    assert 250 <= look["hue"] <= 280
    assert look["sat"] > 80


def test_every_ml100r_gel_produces_a_frame_the_light_takes(caps):
    for gel in gels(caps.color_chip_version):
        state = apply_patch(LightState(), {"mode": "gel", "gel": {k: gel[k] for k in ("version", "brand", "number", "sub_brand", "label", "hex")}}, caps)
        frame = mode_frame(state, caps)
        assert frame[0] in (SUB_SET_CCT, SUB_HSI), gel["label"]
        assert len(frame) == 8  # one packet: as fast as any other change


def test_lights_with_a_gel_mode_still_get_native_gels():
    from lumen_studio.catalog import _caps_table

    rid = next(r for r, row in _caps_table().items() if isinstance(row, dict) and "color_chip" in row.get("modes", []))
    native = model_caps(rid)
    gel = gels(native.color_chip_version)[0]
    state = apply_patch(LightState(), {"mode": "gel", "gel": {k: gel[k] for k in ("version", "brand", "number", "sub_brand", "label", "hex")}}, native)
    assert mode_frame(state, native)[0] in (SUB_COLOR_CHIP_EX, 0xF4)
