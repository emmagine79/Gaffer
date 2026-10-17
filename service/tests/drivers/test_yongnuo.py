"""Yongnuo driver: the bytes it writes, how it powers off, what it matches.

Writes go to a fake transport that records bytes. Nothing here opens Bluetooth.
Expected bytes are written out by hand from the Dart encoder's rules
(asidjwiaijd ble_protocol.dart, no Dart SDK on this Mac) and from the Mifaiyang README.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from gaffer.drivers.yongnuo import YongnuoDriver, load_models
from gaffer.drivers.yongnuo.protocol import decode_decimal, decode_plain, encode_decimal, encode_plain
from gaffer.state import Cct, LightState


class FakeTransport:
    sent: list[bytes] = []

    def __init__(self, address: str) -> None:
        self.address = address
        self._up = False

    async def connect(self) -> None:
        self._up = True

    async def write(self, data: bytes) -> None:
        FakeTransport.sent.append(bytes(data))

    async def disconnect(self) -> None:
        self._up = False

    @property
    def connected(self) -> bool:
        return self._up


@pytest.fixture
def driver():
    FakeTransport.sent = []
    return YongnuoDriver(transport_factory=FakeTransport)


def light(model: str, channel: int) -> SimpleNamespace:
    return SimpleNamespace(address=f"FAKE-{model}-{channel}", model_id=model, channel=channel)


def hexes() -> list[str]:
    return [b.hex().upper() for b in FakeTransport.sent]


async def test_decimal_and_plain_variants_write_exact_bytes(driver):
    # Decimal: pinned capture from the Dart repo (channel 7, 3300 K, 91.6 %), then two more by hand.
    await driver.apply(light("YNLUX100PRO", 7), LightState(brightness=91.6, cct=Cct(kelvin=3300)))
    await driver.apply(light("YNLUX100PRO", 0), LightState(brightness=100, cct=Cct(kelvin=5600)))
    await driver.apply(light("YNLUX100PRO", 255), LightState(brightness=0.1, cct=Cct(kelvin=2700)))
    # Plain (YN150): power-on frame first, then the level frame. 5300 K = 0x14B4, 90 % = 0x5A.
    await driver.apply(light("YN150", 21), LightState(brightness=90, cct=Cct(kelvin=5300)))
    assert hexes() == [
        "AE0309070CE45BA006",
        "AE030900" "15E0" "64A000",
        "AE0309FF" "0A8C" "00A001",
        "AE0106150156",
        "AE030815" "14B4" "5A56",
    ]


async def test_power_off_is_brightness_zero_on_decimal_and_the_power_frame_on_plain(driver):
    await driver.apply(light("YNLUX100PRO", 7), LightState(power=False, cct=Cct(kelvin=3300)))
    await driver.apply(light("YN150", 21), LightState(power=False))
    assert hexes() == ["AE0309070CE400A000", "AE0106150056"]


def test_yn150_advert_is_listed_as_yongnuo_yn150(driver):
    named = SimpleNamespace(local_name="YN150WY", service_uuids=["f000aa60-0451-4000-b000-000000000000"])
    captain = SimpleNamespace(local_name="YN150Li", service_uuids=["0000feff-0000-1000-8000-00805f9b34fb"])
    other = SimpleNamespace(local_name="Zhiyun PL109", service_uuids=[])
    assert driver.match(named) == "YN150" == driver.match(captain)
    assert driver.match(other) is None
    row = driver.models["YN150"]
    assert (row["brand"], row["name"], row["driver"]) == ("Yongnuo", "YN150", "yongnuo")
    assert row["driver_data"]["frame_variant"] == "plain"


async def test_inputs_outside_the_range_are_clamped_or_refused(driver):
    await driver.apply(light("YN150", 3), LightState(brightness=100, cct=Cct(kelvin=9000)))
    assert hexes()[-1] == "AE030803" "1964" "6456"  # 6500 K = 0x1964, 100 %
    with pytest.raises(ValueError):
        await driver.apply(light("YN150", 256), LightState())
    with pytest.raises(ValueError):
        encode_plain(-1, 5000, 50)


def test_frames_round_trip():
    for channel in (0, 1, 21, 255):
        for kelvin in (2700, 3300, 5600, 6500):
            for tenths in (0, 1, 916, 999, 1000):
                assert decode_decimal(encode_decimal(channel, kelvin, tenths / 10)) == (channel, kelvin, tenths / 10)
            for pct in (0, 1, 90, 100):
                assert decode_plain(encode_plain(channel, kelvin, pct)) == (channel, kelvin, pct)


def test_model_files_load():
    assert set(load_models()) == {"YN150", "YNLUX100PRO"}
