"""Every model in the catalogue: what kind of light it is, and what the studio offers it."""

from __future__ import annotations

import random

import pytest
from godox_mesh_bt.protocol import FX_V3

from lumen_studio.adapt import adapt_frame, adapt_state
from lumen_studio.catalog import gels, model_caps, models_index
from lumen_studio.effects import REGISTRY
from lumen_studio.effects.base import Frame
from lumen_studio.effects.profile import effect_profile
from lumen_studio.engine import frame_to_state
from lumen_studio.frames import mode_frame
from lumen_studio.state import Cct, Fx, Gel, Hsi, LightState, Rgbw, validate

ML100R, SL60IIBI, SL100D, CL10, RF1, LT1, TL60, ML60IIBI = (
    "008F", "003A", "000E", "0007", "0025", "00CF", "0001", "0065",
)
CONTROLLABLE = [row["radio_id"] for row in models_index() if row["kind"] != "unsupported"]


# -- what kind of light ---------------------------------------------------------


@pytest.mark.parametrize(
    ("radio_id", "kind"),
    [(ML100R, "rgb"), (SL60IIBI, "bicolour"), (SL100D, "daylight"), (CL10, "colour"),
     (RF1, "unsupported"), (LT1, "unsupported")],
)
def test_each_model_is_classified_from_its_catalogue_modes(radio_id, kind):
    assert model_caps(radio_id).kind == kind


def test_the_index_covers_the_whole_catalogue_sorted_by_name():
    rows = models_index()
    assert len(rows) == 186
    assert [r["name"].lower() for r in rows] == sorted(r["name"].lower() for r in rows)
    assert {"radio_id", "name", "kind", "kind_label"} <= set(rows[0])


def test_an_unknown_model_gets_a_safe_bicolour_default():
    caps = model_caps("ffff")
    assert not caps.known
    assert caps.kind == "bicolour"
    assert (caps.min_kelvin, caps.max_kelvin) == (2800, 6500)
    assert caps.effects == ()
    assert "FFFF" in caps.name


def test_features_say_what_each_light_can_do():
    rgb = model_caps(ML100R).features
    assert rgb["white"] and rgb["colour"] and rgb["channels"] and rgb["tint"] and rgb["fan"]
    assert rgb["gels"] == "emulated"  # no gel mode over Bluetooth on this model
    bi = model_caps(SL60IIBI).features
    assert bi["white"] and not bi["colour"] and not bi["channels"] and not bi["tint"]
    assert bi["gels"] == "white"  # correction gels, as colour temperature
    day = model_caps(SL100D).features
    assert day["daylight"] and day["gels"] is None
    assert model_caps(TL60).features["gels"] == "native"


def test_battery_and_device_settings_follow_the_catalogue():
    ms60r = model_caps("0078")
    assert ms60r.features["battery"] and ms60r.features["fan"]
    assert not model_caps(ML100R).features["battery"]


# -- built-in effects -----------------------------------------------------------------


def test_older_effects_expose_their_gears_as_a_speed_range():
    tl60 = model_caps(TL60)
    assert tl60.effect_version == 0
    cycle = next(e for e in tl60.effects if e.name == "RGB Cycle")
    assert cycle.speed_max == 2  # three gears: 0, 1, 2
    assert cycle.params == ()


def test_newer_effects_are_limited_to_frames_the_library_can_build():
    for radio_id in CONTROLLABLE:
        caps = model_caps(radio_id)
        if caps.effect_version == 1:
            assert all(e.symbol in FX_V3 for e in caps.effects), caps.name


# -- gels -----------------------------------------------------------------------------


def test_a_white_only_light_is_offered_correction_gels_only():
    caps = model_caps(SL60IIBI)
    options = caps.gel_table()
    assert options, "bi-colour lights still get the correction gels"
    assert all(g["how"] == "white" for g in options)
    assert len(options) < len(gels(2)) / 2


def test_a_native_gel_light_gets_its_own_catalogue_version():
    caps = model_caps(TL60)
    table = caps.gel_table()
    assert table and all(g["how"] == "native" and g["version"] == caps.color_chip_version for g in table)


def test_a_daylight_light_without_tint_has_no_gels():
    assert model_caps(SL100D).gel_table() == ()


# -- adapting frames --------------------------------------------------------------------


def test_colour_on_a_white_only_light_becomes_warmth():
    caps = model_caps(SL60IIBI)
    red = adapt_frame(Frame("hsi", 60, hue=0, sat=100), caps)
    blue = adapt_frame(Frame("hsi", 60, hue=230, sat=100), caps)
    assert red.mode == blue.mode == "cct"
    assert red.kelvin == caps.min_kelvin and blue.kelvin == caps.max_kelvin
    assert red.brightness == blue.brightness == 60


def test_a_pale_colour_stays_near_neutral_white():
    caps = model_caps(SL60IIBI)
    pale = adapt_frame(Frame("hsi", 40, hue=30, sat=8), caps)
    assert 4000 < pale.kelvin < 6500


def test_green_and_magenta_use_the_tint_axis_when_there_is_one():
    sl300bi = model_caps("00D0")  # bi-colour with a green/magenta control
    assert sl300bi.kind == "bicolour" and sl300bi.has_tint
    green = adapt_frame(Frame("hsi", 50, hue=120, sat=100), sl300bi)
    magenta = adapt_frame(Frame("hsi", 50, hue=300, sat=100), sl300bi)
    assert green.gm < 0 < magenta.gm
    no_tint = adapt_frame(Frame("hsi", 50, hue=120, sat=100), model_caps(ML60IIBI))
    assert no_tint.gm == 0


def test_white_on_a_colour_only_light_becomes_the_matching_hue():
    warm = adapt_frame(Frame("cct", 70, kelvin=2700), model_caps(CL10))
    assert warm.mode == "hsi" and 15 <= warm.hue <= 45 and warm.sat > 20


def test_channels_become_hsi_on_a_light_without_them():
    caps = model_caps("0089")  # MA5R has HSI but no direct channels
    frame = adapt_frame(Frame("rgbw", 50, rgbw=(1000, 0, 0, 0)), caps)
    assert frame.mode == "hsi" and frame.hue == pytest.approx(0, abs=1) and frame.sat > 95


def test_a_daylight_light_keeps_only_the_brightness():
    caps = model_caps(SL100D)
    frame = adapt_frame(Frame("hsi", 33, hue=120, sat=100), caps)
    assert (frame.mode, frame.kelvin, frame.brightness) == ("cct", 5600, 33)


def test_frames_the_light_can_show_pass_through_untouched():
    caps = model_caps(ML100R)
    frame = Frame("hsi", 50, hue=200, sat=80)
    assert adapt_frame(frame, caps) is frame


# -- adapting whole states, for every model ----------------------------------------------

STATES = [
    LightState(),
    LightState(mode="cct", cct=Cct(kelvin=1800, gm=-100), brightness=12.5),
    LightState(mode="cct", cct=Cct(kelvin=10000, gm=100)),
    LightState(mode="hsi", hsi=Hsi(hue=300, sat=100)),
    LightState(mode="rgbw", rgbw=Rgbw(r=0, g=1000, b=200, w=100)),
    LightState(mode="gel", gel=Gel(version=2, brand=1, number=286, label="L-GEL COR. 286", hex="#ffb464")),
    LightState(mode="gel", gel=Gel(version=2, brand=1, number=139, label="L-GEL 139", hex="#2a7a3c")),
    LightState(mode="fx", fx=Fx(symbol=6, params={"frequency": 4, "trigger": 0})),
    LightState(mode="fx", fx=Fx(symbol=0, speed=2)),
    LightState(power=False, mode="hsi"),
]


@pytest.mark.parametrize("radio_id", CONTROLLABLE)
def test_any_state_adapts_to_something_every_model_accepts(radio_id):
    caps = model_caps(radio_id)
    for state in STATES:
        adapted = adapt_state(state, caps)
        validate(adapted, caps)
        mode_frame(adapted, caps)  # and it encodes
        assert adapted.power == state.power
        assert adapted.brightness == state.brightness


def test_a_state_the_light_already_accepts_is_left_alone():
    caps = model_caps(ML100R)
    state = LightState(mode="hsi", hsi=Hsi(hue=40, sat=70), brightness=33)
    assert adapt_state(state, caps) == state


def test_a_saturated_gel_on_a_white_only_light_becomes_white():
    caps = model_caps(SL60IIBI)
    green_gel = STATES[6]
    adapted = adapt_state(green_gel, caps)
    assert adapted.mode == "cct"


# -- software effects, on any light ------------------------------------------------------


@pytest.mark.parametrize("radio_id", [SL60IIBI, SL100D, CL10, "0089"])
@pytest.mark.parametrize("effect_id", sorted(REGISTRY))
def test_every_software_effect_runs_on_every_kind_of_light(effect_id, radio_id):
    caps = model_caps(radio_id)
    effect = REGISTRY[effect_id]
    step = effect.factory(random.Random(3))
    params = effect.resolve(None)
    state = LightState()
    for i in range(0, 600, 7):
        state = frame_to_state(state, step(i / 10, params), caps)
        validate(state, caps)
        mode_frame(state, caps)


def test_effect_profiles_tell_colour_from_white_and_motion_from_still():
    assert effect_profile("rainbow") == {"colour": True, "brightness_moves": False}
    assert effect_profile("candle")["colour"] is False
    assert effect_profile("candle")["brightness_moves"] is True
    assert effect_profile("strobe")["brightness_moves"] is True
    assert effect_profile("sunrise")["brightness_moves"] is True
