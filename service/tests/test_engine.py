"""Effects, blending, sync and the engine clock. No hardware."""

from __future__ import annotations

import random

import pytest
from godox_mesh_bt.protocol import build_v2_command

from gaffer.blend import blend
from gaffer.catalog import model_caps
from gaffer.effects import REGISTRY
from gaffer.engine import Engine
from gaffer.state import LightState, apply_patch
from gaffer.sync import CctRecord, HsiRecord, SyncTracker, parse_onoff, parse_record


@pytest.fixture(scope="module")
def caps():
    return model_caps("008F")


# -- effects ---------------------------------------------------------------------


@pytest.mark.parametrize("effect_id", sorted(REGISTRY))
def test_every_effect_renders_valid_frames_for_two_minutes(effect_id, caps):
    effect = REGISTRY[effect_id]
    step = effect.factory(random.Random(7))
    params = effect.resolve({})
    for i in range(0, 120 * 30, 7):  # 30 fps, sampled
        frame = step(i / 30.0, params)
        assert frame.mode in ("cct", "hsi", "rgbw")
        assert 0 <= frame.brightness <= 100
        assert 0 <= frame.hue < 360
        assert 0 <= frame.sat <= 100
        assert 1800 <= frame.kelvin <= 10000


def test_effect_params_are_clamped():
    effect = REGISTRY["strobe"]
    assert effect.resolve({"rate": 999})["rate"] == 12


def test_effect_schema_is_serialisable():
    import json
    json.dumps([e.to_dict() for e in REGISTRY.values()])


def test_storm_trigger_fires_a_strike(caps):
    step = REGISTRY["storm"].factory(random.Random(1))
    params = REGISTRY["storm"].resolve({"rate": 0})
    params["_trigger"] = 0
    assert step(0.0, params).mode == "hsi"  # sky
    params["_trigger"] = 1
    assert step(0.01, params).mode == "cct"  # strike


# -- blend -------------------------------------------------------------------------


def test_blend_within_cct_interpolates_kelvin(caps):
    a = apply_patch(LightState(), {"brightness": 0, "cct": {"kelvin": 2000}}, caps)
    b = apply_patch(LightState(), {"brightness": 100, "cct": {"kelvin": 6000}}, caps)
    mid = blend(a, b, 0.5)
    assert mid.mode == "cct" and mid.cct.kelvin == 4000 and mid.brightness == 50


def test_blend_hue_takes_the_short_way(caps):
    a = apply_patch(LightState(), {"mode": "hsi", "hsi": {"hue": 350}}, caps)
    b = apply_patch(LightState(), {"mode": "hsi", "hsi": {"hue": 10}}, caps)
    assert blend(a, b, 0.5).hsi.hue in (0.0, 360.0)


def test_blend_across_modes_goes_through_colour_and_lands_exactly(caps):
    a = apply_patch(LightState(), {"cct": {"kelvin": 3000}}, caps)
    b = apply_patch(LightState(), {"mode": "hsi", "hsi": {"hue": 240}}, caps)
    assert blend(a, b, 0.5).mode == "hsi"
    assert blend(a, b, 1.0) == b


def test_fade_from_off_uses_the_target_colour(caps):
    a = LightState(power=False)
    b = apply_patch(LightState(), {"mode": "hsi", "hsi": {"hue": 120}, "brightness": 80}, caps)
    mid = blend(a, b, 0.5)
    assert mid.power and mid.mode == "hsi" and mid.hsi.hue == 120 and mid.brightness == 40


# -- sync ------------------------------------------------------------------------------


def test_records_decode_as_measured_on_the_ml100r():
    # Bytes captured from the real light on 2026-10-03.
    assert parse_record(bytes.fromhex("a0463cff00e20015")) == CctRecord(70, 6000, -30)
    assert parse_record(bytes.fromhex("a13cc80050ff0033")) == HsiRecord(60, 200, 80)
    assert parse_record(bytes.fromhex("a20abdfbe74f01eb")) is None  # static flash default
    assert parse_onoff(bytes.fromhex("820401")) is True


def test_tracker_ignores_stale_and_echoes_but_adopts_outside_changes(caps):
    tracker = SyncTracker()
    state = apply_patch(LightState(), {"brightness": 40, "cct": {"kelvin": 3200}}, caps)
    assert tracker.observe(CctRecord(40, 3200, 0), state) is None  # first reading: baseline
    assert tracker.observe(CctRecord(40, 3200, 0), state) is None  # unchanged: stale or steady
    commanded = apply_patch(state, {"brightness": 60}, caps)
    assert tracker.observe(CctRecord(60, 3200, 0), commanded) is None  # our own echo
    patch = tracker.observe(CctRecord(25, 3200, 0), commanded)  # the panel dial
    assert patch == {"mode": "cct", "brightness": 25, "cct": {"kelvin": 3200, "gm": 0}}


def test_effect_frames_are_echoes_not_outside_changes(caps):
    """Regression, seen on hardware: an effect's last HSI frame was adopted as a
    panel change after the effect stopped, flipping the app into HSI mode."""
    from gaffer.frames import mode_frame
    from gaffer.sync import expected_record

    tracker = SyncTracker()
    cct_state = apply_patch(LightState(), {"brightness": 25, "cct": {"kelvin": 3000}}, caps)
    tracker.observe(HsiRecord(33, 20, 100), cct_state)  # baseline from before the effect
    effect_frame = apply_patch(LightState(), {"mode": "hsi", "brightness": 20, "hsi": {"hue": 196, "sat": 99}}, caps)
    tracker.expect(expected_record(mode_frame(effect_frame, caps)))  # the pump sent it
    assert tracker.observe(HsiRecord(20, 196, 99), cct_state) is None


def test_expected_record_decodes_both_command_kinds(caps):
    from gaffer.frames import mode_frame
    from gaffer.sync import expected_record

    cct = apply_patch(LightState(), {"brightness": 40, "cct": {"kelvin": 3200, "gm": -20}}, caps)
    hsi = apply_patch(LightState(), {"mode": "hsi", "brightness": 60, "hsi": {"hue": 300, "sat": 80}}, caps)
    assert expected_record(mode_frame(cct, caps)) == CctRecord(40, 3200, -20)
    assert expected_record(mode_frame(hsi, caps)) == HsiRecord(60, 300, 80)
    assert expected_record(bytes.fromhex("fe00ffffffffff00")) is None


def test_demo_light_records_mirror_real_command_layout(caps):
    from gaffer.frames import mode_frame
    hsi = apply_patch(LightState(), {"mode": "hsi", "brightness": 60, "hsi": {"hue": 200, "sat": 80}}, caps)
    frame = mode_frame(hsi, caps)
    record = build_v2_command(0xA1, 0x00, bytes([frame[1], frame[2], frame[3], frame[4], 0xFF]))
    assert parse_record(record) == HsiRecord(60, 200, 80)


# -- engine ---------------------------------------------------------------------------------


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def _engine(caps, clock):
    box = {"state": LightState()}
    applied: list[LightState] = []

    def apply(s: LightState) -> None:
        box["state"] = s
        applied.append(s)

    eng = Engine(caps, get_state=lambda: box["state"], apply=apply, on_change=lambda _s: None, clock=clock)
    return eng, box, applied


def test_effect_stop_restores_the_previous_look(caps):
    clock = Clock()
    eng, box, _ = _engine(caps, clock)
    before = box["state"]
    eng.start_effect("rainbow")
    clock.t = 3.0
    eng.tick()
    assert box["state"].mode == "hsi"
    eng.stop()
    assert box["state"] == before


def test_transition_finishes_on_the_exact_target(caps):
    clock = Clock()
    eng, box, _applied = _engine(caps, clock)
    target = apply_patch(LightState(), {"brightness": 90, "cct": {"kelvin": 8000}}, caps)
    eng.start_transition(target, 2.0)
    clock.t = 1.0
    eng.tick()
    assert 5600 < box["state"].cct.kelvin < 8000
    clock.t = 2.5
    eng.tick()
    assert box["state"] == target and eng.kind is None


def test_timeline_interpolates_between_keyframes(caps):
    clock = Clock()
    eng, box, _ = _engine(caps, clock)
    eng.play_timeline({"keyframes": [
        {"t": 0, "state": {"brightness": 0}},
        {"t": 4, "state": {"brightness": 80}, "ease": "linear"},
    ]})
    clock.t = 2.0
    eng.tick()
    assert box["state"].brightness == 40


def test_schedule_fires_in_its_minute_on_its_days():
    from datetime import UTC, datetime

    from gaffer.scheduler import due
    monday_7 = datetime(2026, 10, 5, 7, 0, 30, tzinfo=UTC)  # a Monday
    alarm = {"enabled": True, "at": "07:00", "days": [0, 1, 2, 3, 4]}
    assert due(alarm, monday_7)
    assert not due(alarm, monday_7.replace(minute=1))
    assert not due({**alarm, "days": [5, 6]}, monday_7)
    assert not due({**alarm, "enabled": False}, monday_7)
    assert not due({**alarm, "at": "bad"}, monday_7)


def test_morse_timeline_spells_sos():
    from gaffer.effects.signature import morse_timeline
    on = [u for is_on, u in morse_timeline("SOS") if is_on]
    assert on == [1, 1, 1, 3, 3, 3, 1, 1, 1]


def test_photo_booth_counts_down_then_flashes():
    effect = REGISTRY["photo-booth"]
    step = effect.factory(random.Random(0))
    p = effect.resolve({"count": 3, "model": 20, "flash": 100})
    p["_trigger"] = 0
    assert step(0.0, p).brightness == 20
    p["_trigger"] = 1
    assert step(1.0, p).brightness == 55  # first blink as the count starts
    assert step(4.1, p).brightness == 100  # flash on zero
    assert step(9.0, p).brightness == 20  # back to modelling light


def test_scan_accepts_long_palettes():
    effect = REGISTRY["scan"]
    colours = [f"#{i:02x}{i:02x}{i:02x}" for i in range(10, 58)]
    assert len(effect.resolve({"colors": colours})["colors"]) == 48


def test_a_silent_stream_ends_but_keeps_its_last_look(caps):
    from gaffer.effects.base import hsi
    clock = Clock()
    eng, box, _ = _engine(caps, clock)
    eng.push_stream(hsi(270, 90, 40), "audio")
    assert eng.kind == "stream"
    clock.t = 2.0
    assert not eng.expire_stream()
    clock.t = 3.5
    assert eng.expire_stream()
    assert eng.kind is None and box["state"].hsi.hue == 270
