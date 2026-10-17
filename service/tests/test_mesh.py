"""Several lights on one mesh: mirroring a look between them, and one pump feeding them all."""

from __future__ import annotations

import asyncio

import pytest

from gaffer.catalog import model_caps
from gaffer.mirror import ALL_PROPS, mirror
from gaffer.pump import CommandPump
from gaffer.state import Cct, Fx, Hsi, LightState, validate

RGB = model_caps("008F")  # ML100R
BI = model_caps("003A")  # SL60IIBi, 2800-6500 K, no colour
DAY = model_caps("000E")  # SL100D, fixed 5600 K


# -- mirroring ------------------------------------------------------------------------


def test_everything_follows_when_every_property_is_synced():
    leader = LightState(mode="hsi", hsi=Hsi(hue=200, sat=80), brightness=42, power=True)
    follower = LightState(mode="cct", brightness=90)
    assert mirror(leader, follower, ALL_PROPS, RGB) == leader.model_copy(update={"cct": follower.cct, "rgbw": follower.rgbw})


def test_only_the_chosen_properties_move():
    leader = LightState(mode="cct", cct=Cct(kelvin=3200), brightness=20, power=False)
    follower = LightState(mode="cct", cct=Cct(kelvin=6000), brightness=80, power=True)
    only_brightness = mirror(leader, follower, frozenset({"brightness"}), RGB)
    assert (only_brightness.brightness, only_brightness.power, only_brightness.cct.kelvin) == (20, True, 6000)
    only_white = mirror(leader, follower, frozenset({"white"}), RGB)
    assert (only_white.cct.kelvin, only_white.brightness) == (3200, 80)


def test_colour_reaches_a_bicolour_light_as_warmth():
    leader = LightState(mode="hsi", hsi=Hsi(hue=0, sat=100), brightness=50)
    follower = mirror(leader, LightState(cct=Cct(kelvin=5600)), frozenset({"colour"}), BI)
    assert follower.mode == "cct" and follower.cct.kelvin == BI.min_kelvin
    validate(follower, BI)


def test_white_is_clamped_to_the_followers_range():
    leader = LightState(mode="cct", cct=Cct(kelvin=1800, gm=-100))
    follower = mirror(leader, LightState(), frozenset({"white"}), BI)
    assert (follower.cct.kelvin, follower.cct.gm) == (2800, 0)
    validate(follower, BI)
    assert mirror(leader, LightState(), frozenset({"white"}), DAY).cct.kelvin == 5600


def test_colour_sync_leaves_a_white_follower_alone_when_colour_is_off():
    leader = LightState(mode="hsi", hsi=Hsi(hue=120, sat=100))
    follower = LightState(mode="cct", cct=Cct(kelvin=4000))
    assert mirror(leader, follower, frozenset({"white"}), BI) == follower


def test_a_built_in_effect_is_matched_by_name_on_the_follower():
    ml100r_lightning = next(e for e in RGB.effects if e.name == "Lightning")
    leader = LightState(mode="fx", fx=Fx(symbol=ml100r_lightning.symbol, params={"frequency": 4}))
    ml60 = model_caps("0065")  # ML60IIBi: older effect generation, different symbols
    theirs = next((e for e in ml60.effects if e.name == "Lightning"), None)
    follower = mirror(leader, LightState(), frozenset({"effects"}), ml60, leader_caps=RGB)
    validate(follower, ml60)
    if theirs is not None:
        assert follower.mode == "fx" and follower.fx.symbol == theirs.symbol


def test_an_effect_the_follower_lacks_leaves_its_look_unchanged():
    leader = LightState(mode="fx", fx=Fx(symbol=next(e.symbol for e in RGB.effects if e.name == "RGB Cycle")))
    follower = LightState(mode="cct", cct=Cct(kelvin=4000), brightness=60)
    result = mirror(leader, follower, frozenset({"effects"}), DAY, leader_caps=RGB)
    assert (result.mode, result.cct.kelvin, result.brightness) == ("cct", 5600, 60)


# -- one pump, many lights ---------------------------------------------------------------


class Recorder:
    def __init__(self, delay: float = 0.0) -> None:
        self.sent: list[tuple[int | None, bytes]] = []
        self.delay = delay

    async def __call__(self, frame: bytes, dst: int | None) -> None:
        await asyncio.sleep(self.delay)
        self.sent.append((dst, frame))


async def _drain(pump: CommandPump, recorder: Recorder, rounds: int = 40) -> None:
    for _ in range(rounds):
        await asyncio.sleep(0.005)


async def test_each_light_gets_its_own_frames_at_its_own_address():
    pump = CommandPump(RGB, max_rate=1000)
    recorder = Recorder()
    pump.attach(recorder)
    task = asyncio.create_task(pump.run())
    pump.submit(LightState(cct=Cct(kelvin=3200)), node=2, caps=RGB)
    pump.submit(LightState(cct=Cct(kelvin=3200)), node=4, caps=BI)
    await _drain(pump, recorder)
    task.cancel()
    assert {dst for dst, _ in recorder.sent} == {2, 4}


async def test_lights_take_turns_so_a_busy_one_cannot_starve_the_rest():
    pump = CommandPump(RGB, max_rate=1000)
    recorder = Recorder(delay=0.002)
    pump.attach(recorder)
    task = asyncio.create_task(pump.run())
    for i in range(30):
        pump.submit(LightState(brightness=float(i + 1)), node=2, caps=RGB)
        if i == 5:
            pump.submit(LightState(brightness=77.0), node=4, caps=RGB)
        await asyncio.sleep(0.001)
    await _drain(pump, recorder)
    task.cancel()
    assert any(dst == 4 for dst, _ in recorder.sent)
    last_for_2 = [frame for dst, frame in recorder.sent if dst == 2][-1]
    assert last_for_2[1] == 30  # the newest brightness for light 2 still lands


async def test_diffing_is_per_light():
    pump = CommandPump(RGB, max_rate=1000, sleep=lambda _s: asyncio.sleep(0))  # no power-on settle
    recorder = Recorder()
    pump.attach(recorder)
    task = asyncio.create_task(pump.run())
    look = LightState(cct=Cct(kelvin=4000))
    pump.submit(look, node=2, caps=RGB)
    await _drain(pump, recorder, 10)
    pump.submit(look, node=4, caps=RGB)  # same look, different light: must still be sent
    pump.submit(look, node=2, caps=RGB)  # same look, same light: skipped
    await _drain(pump, recorder, 10)
    task.cancel()
    assert sum(1 for dst, _ in recorder.sent if dst == 4) == 2  # power on + mode
    assert sum(1 for dst, _ in recorder.sent if dst == 2) == 2


@pytest.mark.parametrize("radio_id", ["008F", "003A", "000E", "0007", "0001"])
def test_mirroring_always_yields_a_state_the_follower_accepts(radio_id):
    caps = model_caps(radio_id)
    leaders = [
        LightState(mode="hsi", hsi=Hsi(hue=300, sat=90)),
        LightState(mode="cct", cct=Cct(kelvin=10000, gm=100)),
        LightState(mode="fx", fx=Fx(symbol=6)),
        LightState(power=False),
    ]
    for leader in leaders:
        validate(mirror(leader, LightState(cct=Cct(kelvin=caps.min_kelvin or 5600)), ALL_PROPS, caps, leader_caps=RGB), caps)
