"""Zhiyun driver: bytes equal what didim99/HA-Zhiyun-Light writes, models and matching, input safety.

Everything runs against a fake transport that records bytes. Nothing opens Bluetooth.
The fixture zhiyun_ha_frames.json was recorded by fixtures/record_zhiyun_ha.py from the real HA module.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from gaffer.drivers import Driver
from gaffer.drivers.base import Advert
from gaffer.drivers.zhiyun import ZhiyunDriver, protocol as p
from gaffer.drivers.zhiyun.models import load_models, resolve_model
from gaffer.drivers.zhiyun.transport import LinkError
from gaffer.scan import summarize
from gaffer.state import Cct, LightState

HA = json.loads((Path(__file__).parent / "fixtures" / "zhiyun_ha_frames.json").read_text())
HANDSHAKE = 5  # frames the driver writes on connect before any command


# -- a transport that records bytes ---------------------------------------------


class FakeLink:
    def __init__(self, transport):
        self.t = transport
        self.connected = True

    async def write(self, data: bytes) -> None:
        if self.t.fail_writes:
            raise LinkError("write_failed", "The light did not accept the command.")
        self.t.writes.append(data.hex())

    async def close(self) -> None:
        self.connected = False


class FakeTransport:
    def __init__(self):
        self.writes: list[str] = []
        self.opens = 0
        self.fail_writes = False

    async def open(self, address, on_notify, on_lost):
        self.opens += 1
        return FakeLink(self)


class Light:
    id, name, address, radio_id = "z1", "PL109_C75E", "00000000-0000-0000-0000-000000000001", "PL109"


async def nosleep(_s: float) -> None:
    pass


def make():
    transport = FakeTransport()
    return ZhiyunDriver(transport=transport, sleep=nosleep), transport


def on(brightness: float, kelvin: int) -> LightState:
    return LightState(power=True, brightness=brightness, cct=Cct(kelvin=kelvin))


async def run(driver, steps):
    light = Light()
    await driver.connect(light)
    for state in steps:
        driver.apply(light, state)
        await driver.flush(light)
    await driver.stop()


# -- AC1: apply() writes the bytes HA writes -------------------------------------

A = on(37.5, 4300)
SESSIONS = {
    "on_37_5_4300": [A],
    "on_then_brightness_80": [A, on(80, 4300)],
    "on_then_cct_3200": [A, on(37.5, 3200)],
    "on_then_brightness_0": [A, on(0, 4300)],
    "on_then_off": [A, LightState(power=False)],
    "on_off_on_again": [A, LightState(power=False), A],
    "off_first": [LightState(power=False)],
    "on_clamped_below_1000": [on(37.5, 1000)],
    # LightState caps brightness at 100, so build the out-of-range one the way a bug would.
    "on_clamped_250_9000": [LightState.model_construct(power=True, brightness=250.0, cct=Cct(kelvin=9000))],
}


@pytest.mark.parametrize("name", sorted(SESSIONS))
async def test_apply_writes_the_bytes_ha_zhiyun_light_writes(name):
    driver, transport = make()
    await run(driver, SESSIONS[name])
    assert transport.writes == HA["sessions"][name]


def test_encoders_equal_ha_packets_for_every_recorded_sequence_number():
    for seq in (0, 1, 7, 65535):
        rec = HA["packets"][f"seq{seq}"]
        built = {
            "power_on": p.build_packet(p.Command.POWER_STATE, p.encode_power(True), seq),
            "power_off": p.build_packet(p.Command.POWER_STATE, p.encode_power(False), seq),
            "brightness_0": p.build_packet(p.Command.SET_BRIGHTNESS, p.encode_brightness(0), seq),
            "brightness_37_5": p.build_packet(p.Command.SET_BRIGHTNESS, p.encode_brightness(37.5), seq),
            "brightness_100": p.build_packet(p.Command.SET_BRIGHTNESS, p.encode_brightness(100), seq),
            "cct_2700": p.build_packet(p.Command.SET_COLOR_TEMP, p.encode_color_temp(2700), seq),
            "cct_4300": p.build_packet(p.Command.SET_COLOR_TEMP, p.encode_color_temp(4300), seq),
            "cct_6500": p.build_packet(p.Command.SET_COLOR_TEMP, p.encode_color_temp(6500), seq),
            "query": p.build_packet(p.Command.READ_DEVICE_STATE, p.encode_query(), seq),
        }
        assert {k: v.hex() for k, v in built.items()} == rec


# -- AC2: zyframe.py and the port agree ------------------------------------------


def _zyframe():
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "zyframe.py"
        if candidate.is_file():
            spec = importlib.util.spec_from_file_location("zyframe", candidate)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    return None


@pytest.mark.parametrize("op", p.VALID_OPS)
def test_port_frames_equal_zyframe_for_the_same_cid_object_op_and_args(op):
    zy = _zyframe()
    if zy is None:
        pytest.skip("zyframe.py (Captain's research file) is not beside this checkout")
    for seq in (0, 5, 65535):
        for cid, payload in (
            (p.Command.POWER_STATE, p.encode_power(True, op)),
            (p.Command.SET_BRIGHTNESS, p.encode_brightness(62.5, op)),
            (p.Command.SET_COLOR_TEMP, p.encode_color_temp(5600, op)),
        ):
            args = payload[3:]  # after the object id (2 bytes) and op (1 byte)
            assert p.build_packet(cid, payload, seq) == zy.frame(int(cid), p.CONTROL_OBJECT, op, args, seq)


def test_port_decoder_agrees_with_ha_decoder_and_rejects_a_bad_crc():
    for name, expected in HA["parsed"].items():
        r = p.parse_frame(bytes.fromhex(HA["packets"]["seq1"][name]))
        assert (r.command, r.sequence, r.payload.hex()) == (expected["command"], expected["sequence"], expected["payload"])
    bad = bytearray.fromhex(HA["packets"]["seq1"]["power_on"])
    bad[-1] ^= 0xFF
    assert HA["bad_crc_rejected"]
    with pytest.raises(p.ProtocolError):
        p.parse_frame(bytes(bad))


# -- AC3: models and matching ------------------------------------------------------


def test_pl109_resolves_to_molus_g200_and_the_scan_lists_it_by_that_name():
    assert resolve_model("PL109_C75E")["name"] == "MOLUS G200"

    class Adv:  # a real G200: mesh service 0x1828 and no 0xFEE9
        local_name = "PL109_C75E"
        rssi = -60
        service_uuids = ["00001828-0000-1000-8000-00805f9b34fb"]
        service_data: dict = {}
        manufacturer_data: dict = {}

    class Dev:
        name = "PL109_C75E"

    entry = summarize({"id-1": (Dev(), Adv())})["devices"][0]
    assert (entry["name"], entry["family"]) == ("PL109_C75E", "zhiyun")


def test_one_model_file_per_ha_model_and_the_driver_matches_by_name_prefix():
    assert {k: v["name"] for k, v in load_models().items()} == HA["model_names"]
    driver, _ = make()
    assert driver.match(Advert(address="x", name="PL109_C75E", services=("00001828-0000-1000-8000-00805f9b34fb",))) == "PL109"
    assert driver.match(Advert(address="x", name="PLG105_0001")) == "PLG105"
    assert driver.match(Advert(address="x", name="Some Speaker")) is None
    assert driver.match(Advert(address="x", name=None)) is None


def test_the_driver_registry_finds_the_zhiyun_driver():
    # SPEC-003 ships the Driver base class; subclasses are its registry until a discover() lands.
    ids = {cls.id: cls for cls in Driver.__subclasses__()}
    assert ids["zhiyun"] is ZhiyunDriver


# -- input safety (checklist 6) ------------------------------------------------------


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True, "50", None])
def test_encoders_refuse_values_that_are_not_finite_numbers(bad):
    with pytest.raises(p.ProtocolError):
        p.encode_brightness(bad)
    with pytest.raises(p.ProtocolError):
        p.encode_color_temp(bad)


def test_op_byte_must_be_a_known_one_and_the_model_range_clamps_kelvin():
    with pytest.raises(p.ProtocolError):
        p.encode_power(True, op=0x7F)
    assert p.encode_color_temp(9000, lo=2700, hi=5600) == p.encode_color_temp(5600)
    assert p.encode_brightness(-5) == p.encode_brightness(0)


# -- failure handling ------------------------------------------------------------------


async def test_a_failed_write_marks_the_light_unreachable_and_the_next_apply_reconnects_and_resends():
    driver, transport = make()
    light = Light()
    await driver.connect(light)
    transport.fail_writes = True
    driver.apply(light, A)
    await driver.flush(light)
    assert driver.status(light) == {"reachable": False, "held": False}
    transport.fail_writes = False
    transport.writes.clear()
    driver.apply(light, A)
    await driver.flush(light)
    assert transport.opens == 2
    assert driver.status(light)["reachable"] is True
    # full handshake again, then power, colour temperature, brightness
    assert len(transport.writes) == HANDSHAKE + 3
    await driver.stop()
