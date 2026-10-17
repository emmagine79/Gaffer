"""Zhiyun driver: bytes equal what didim99/HA-Zhiyun-Light writes, models and matching, input safety.

Everything runs against a fake transport that records bytes. Nothing opens Bluetooth.
The fixture zhiyun_ha_frames.json was recorded by fixtures/record_zhiyun_ha.py from the real HA module.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import struct
from pathlib import Path

import pytest

from gaffer.drivers import Driver
from gaffer.drivers.base import Advert
from gaffer.drivers.zhiyun import ZhiyunDriver, protocol as p
from gaffer.drivers.zhiyun import transport as transport_module
from gaffer.drivers.zhiyun.driver import IDENTIFY_HOLD_SECONDS, ZhiyunError
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
        if self.t.hang_after is not None and len(self.t.writes) >= self.t.hang_after:
            await asyncio.Event().wait()  # a write that never completes
        self.t.writes.append(data.hex())

    async def close(self) -> None:
        self.connected = False


class FakeTransport:
    def __init__(self):
        self.writes: list[str] = []
        self.opens = 0
        self.fail_writes = False
        self.fail_open = False
        self.hang_after: int | None = None  # writes allowed before one blocks forever
        self.lost_callbacks: list = []  # the on_lost callback of each link, oldest first

    async def open(self, address, on_notify, on_lost):
        if self.fail_open:
            raise LinkError("connect_failed", "Could not connect to the light.")
        self.opens += 1
        self.lost_callbacks.append(on_lost)
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


def commands(transport) -> list[p.Response]:
    """The frames written after the connect handshake, decoded."""
    return [p.parse_frame(bytes.fromhex(w)) for w in transport.writes[HANDSHAKE:]]


def last_value(transport, command: p.Command, fmt: str) -> float:
    """The last value written for ``command`` (after the object id and op byte)."""
    frames = [c for c in commands(transport) if c.command == command]
    return struct.unpack(fmt, frames[-1].payload[3:])[0]


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
    """Captain's research file, copied unchanged into fixtures/ so this test always runs."""
    spec = importlib.util.spec_from_file_location("zyframe", Path(__file__).parent / "fixtures" / "zyframe.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("op", p.VALID_OPS)
def test_port_frames_equal_zyframe_for_the_same_cid_object_op_and_args(op):
    zy = _zyframe()
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


async def test_a_late_disconnect_callback_from_a_replaced_link_does_not_drop_the_live_link():
    driver, transport = make()
    light = Light()
    await driver.connect(light)
    transport.fail_writes = True
    driver.apply(light, A)
    await driver.flush(light)  # link 1 failed and was replaced
    transport.fail_writes = False
    driver.apply(light, A)
    await driver.flush(light)
    assert transport.opens == 2
    transport.lost_callbacks[0]()  # bleak reports link 1's disconnect late
    assert driver.status(light)["reachable"] is True
    driver.apply(light, on(80, 4300))
    await driver.flush(light)
    assert transport.opens == 2  # no third connection
    transport.lost_callbacks[1]()  # the live link really drops
    assert driver.status(light)["reachable"] is False
    await driver.stop()


async def test_a_link_whose_handshake_was_cut_short_is_not_reused_without_one():
    driver, transport = make()
    light = Light()
    transport.hang_after = 3  # the fourth handshake frame never completes
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(driver.connect(light), 0.05)  # a caller gives up: the connect is cancelled
    assert driver.status(light)["reachable"] is not True
    transport.hang_after = None
    transport.writes.clear()
    driver.apply(light, A)
    await driver.flush(light)
    assert transport.opens == 2
    assert len(transport.writes) == HANDSHAKE + 3  # a full handshake, then the command
    await driver.stop()


async def test_stop_releases_a_caller_waiting_on_flush_and_nothing_reconnects_after_it():
    driver, transport = make()
    light = Light()
    transport.hang_after = 0  # the light stops answering mid-handshake
    driver.apply(light, A)
    waiting = asyncio.ensure_future(driver.flush(light))
    for _ in range(5):
        await asyncio.sleep(0)
    await driver.stop()
    await asyncio.wait_for(waiting, 1)
    driver.apply(light, A)  # a late caller, such as an identify that was mid-pulse
    await driver.flush(light)
    assert transport.opens == 1


# -- identify -----------------------------------------------------------------------------


async def test_identify_does_not_switch_off_a_light_it_never_commanded():
    driver, transport = make()
    light = Light()
    await driver.connect(light)
    await driver.identify(light)
    powers = [c.payload[-1] for c in commands(transport) if c.command == p.Command.POWER_STATE]
    assert powers and powers[-1] == 1
    await driver.stop()


async def test_identify_leaves_a_change_made_during_the_pulse_alone():
    driver = None
    changed = False

    async def sleep(seconds: float) -> None:
        nonlocal changed
        if seconds == IDENTIFY_HOLD_SECONDS and not changed:
            changed = True
            driver.apply(light, on(20, 3000))  # a fader moves while the light pulses

    transport = FakeTransport()
    driver = ZhiyunDriver(transport=transport, sleep=sleep)
    light = Light()
    await driver.connect(light)
    driver.apply(light, A)
    await driver.flush(light)
    await driver.identify(light)
    await driver.flush(light)
    assert last_value(transport, p.Command.SET_BRIGHTNESS, "<f") == 20.0
    assert last_value(transport, p.Command.SET_COLOR_TEMP, "<H") == 3000
    await driver.stop()


async def test_identify_tells_the_caller_when_the_light_does_not_answer():
    driver, transport = make()
    transport.fail_open = True
    with pytest.raises(ZhiyunError):
        await driver.identify(Light())
    await driver.stop()


# -- the Bluetooth transport, with bleak's client replaced by a stand-in --------------------


class FakeBleakClient:
    """Stands in for bleak's BleakClient: the operating system is the only thing not real."""

    instances: list = []
    connect_hangs = False
    notify_error: Exception | None = None

    def __init__(self, address, disconnected_callback=None):
        self.is_connected = False
        self.disconnected = False
        FakeBleakClient.instances.append(self)

        char = type("Char", (), {})()
        service = type("Service", (), {"get_characteristic": lambda _s, _uuid: char})()
        self.services = type("Services", (), {"get_service": lambda _s, _uuid: service})()

    async def connect(self):
        if FakeBleakClient.connect_hangs:
            await asyncio.Event().wait()
        self.is_connected = True

    async def start_notify(self, _char, _callback):
        if FakeBleakClient.notify_error:
            raise FakeBleakClient.notify_error

    async def disconnect(self):
        self.disconnected = True
        self.is_connected = False


@pytest.fixture
def fake_bleak(monkeypatch):
    monkeypatch.setattr("bleak.BleakClient", FakeBleakClient)
    FakeBleakClient.instances = []
    FakeBleakClient.connect_hangs = False
    FakeBleakClient.notify_error = None
    return FakeBleakClient


async def test_a_light_that_drops_during_notify_setup_is_a_link_error_and_the_client_is_released(fake_bleak):
    from bleak.exc import BleakError

    fake_bleak.notify_error = BleakError("dropped")
    with pytest.raises(LinkError):
        await transport_module.BleakTransport().open("addr", lambda _d: None, lambda: None)
    assert fake_bleak.instances[0].disconnected


async def test_a_connect_that_times_out_releases_the_client(fake_bleak, monkeypatch):
    monkeypatch.setattr(transport_module, "CONNECT_TIMEOUT", 0.05)
    fake_bleak.connect_hangs = True
    with pytest.raises(LinkError):
        await transport_module.BleakTransport().open("addr", lambda _d: None, lambda: None)
    assert fake_bleak.instances[0].disconnected
