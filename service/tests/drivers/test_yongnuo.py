"""Yongnuo driver: the bytes it writes, how it powers off, what it matches.

Writes go to a fake transport that records bytes. Nothing here opens Bluetooth.
Expected bytes are written out by hand from the Dart encoder's rules
(asidjwiaijd ble_protocol.dart, no Dart SDK on this Mac) and from the Mifaiyang README.
"""

from __future__ import annotations

from types import SimpleNamespace

import asyncio
import importlib
import pkgutil

import pytest
import pytest_asyncio

import gaffer.drivers
from gaffer.drivers.base import Advert, Driver
from gaffer.drivers.yongnuo import YongnuoDriver, retry_delay
from gaffer.drivers.yongnuo.protocol import encode_plain
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
    return SimpleNamespace(id=f"l-{model}-{channel}", address=f"FAKE-{model}-{channel}", radio_id=model, channel=channel)


def hexes() -> list[str]:
    return [b.hex().upper() for b in FakeTransport.sent]


async def test_decimal_and_plain_variants_write_exact_bytes(driver):
    # Decimal: pinned capture from the Dart repo (channel 7, 3300 K, 91.6 %), then two more by hand.
    driver.apply(light("YNLUX100PRO", 7), LightState(brightness=91.6, cct=Cct(kelvin=3300)))
    await driver.flush()
    driver.apply(light("YNLUX100PRO", 0), LightState(brightness=100, cct=Cct(kelvin=5600)))
    await driver.flush()
    driver.apply(light("YNLUX100PRO", 255), LightState(brightness=0.1, cct=Cct(kelvin=2700)))
    await driver.flush()
    # Plain (YN150): power-on frame first, then the level frame. 5300 K = 0x14B4, 90 % = 0x5A.
    driver.apply(light("YN150", 21), LightState(brightness=90, cct=Cct(kelvin=5300)))
    await driver.flush()
    assert hexes() == [
        "AE0309070CE45BA006",
        "AE030900" "15E0" "64A000",
        "AE0309FF" "0A8C" "00A001",
        "AE0106150156",
        "AE030815" "14B4" "5A56",
    ]


async def test_power_off_is_brightness_zero_on_decimal_and_the_power_frame_on_plain(driver):
    driver.apply(light("YNLUX100PRO", 7), LightState(power=False, cct=Cct(kelvin=3300)))
    await driver.flush()
    driver.apply(light("YN150", 21), LightState(power=False))
    await driver.flush()
    assert hexes() == ["AE0309070CE400A000", "AE0106150056"]


def test_yn150_advert_is_listed_as_yongnuo_yn150(driver):
    named = Advert(address="a", name="YN150WY", services=("f000aa60-0451-4000-b000-000000000000",))
    captain = Advert(address="b", name="YN150Li", services=("0000feff-0000-1000-8000-00805f9b34fb",))
    other = Advert(address="c", name="Zhiyun PL109")
    assert driver.match(named) == "YN150" == driver.match(captain)
    assert driver.match(other) is None
    row = driver.models["YN150"]
    assert (row["brand"], row["name"], row["driver"]) == ("Yongnuo", "YN150", "yongnuo")
    assert row["driver_data"]["frame_variant"] == "plain"


def test_the_driver_is_found_by_the_registry_rule_and_matches_a_yn150li_advert():
    # The rule in gaffer/drivers/base.py: import every sub-package, take each concrete Driver.
    for info in pkgutil.iter_modules(gaffer.drivers.__path__):
        if info.ispkg:
            importlib.import_module(f"gaffer.drivers.{info.name}")
    found = {cls.id: cls for cls in Driver.__subclasses__() if not getattr(cls, "__abstractmethods__", None)}
    assert "yongnuo" in found
    advert = Advert(address="x", name="YN150Li", services=("0000feff-0000-1000-8000-00805f9b34fb",))
    assert found["yongnuo"]().match(advert) == "YN150"


async def test_inputs_outside_the_range_are_clamped_or_refused(driver):
    driver.apply(light("YN150", 3), LightState(brightness=100, cct=Cct(kelvin=9000)))
    await driver.flush()
    assert hexes()[-1] == "AE030803" "1964" "6456"  # 6500 K = 0x1964, 100 %
    with pytest.raises(ValueError):
        driver.apply(light("YN150", 256), LightState())
    with pytest.raises(ValueError):
        encode_plain(-1, 5000, 50)


# -- what the light does when Bluetooth misbehaves ---------------------------------------------
# The driver is given a transport that fails on demand. Nothing opens Bluetooth. The retry delay
# is a recorded fake sleep, so no test waits on a clock.


class Scripted:
    """A transport per address that connects, writes and disconnects as the test scripts it."""

    def __init__(self) -> None:
        self.made: list[FlakyTransport] = []
        self.sent: dict[str, list[str]] = {}
        self.write_failures = 0  # the next N writes (any light) raise
        self.write_error: Exception = OSError("write failed")
        self.slow: set[str] = set()  # these addresses' connect waits for .release before it succeeds
        self.release = asyncio.Event()
        self.dead: set[str] = set()  # these addresses never connect: connect raises
        self.hung: set[str] = set()  # these addresses' connect never returns
        self.connect_attempts: dict[str, int] = {}
        self.stuck_connected = False  # a failed write leaves .connected True, as bleak can
        self.disconnect_raises: set[str] = set()

    def __call__(self, address: str) -> "FlakyTransport":
        transport = FlakyTransport(self, address)
        self.made.append(transport)
        return transport

    def bytes_for(self, address: str) -> list[str]:
        return self.sent.get(address, [])


class FlakyTransport:
    def __init__(self, script: Scripted, address: str) -> None:
        self.script, self.address, self._up, self.disconnected = script, address, False, False

    async def connect(self) -> None:
        self.script.connect_attempts[self.address] = self.script.connect_attempts.get(self.address, 0) + 1
        await asyncio.sleep(0)
        if self.address in self.script.hung:
            await asyncio.Event().wait()
        if self.address in self.script.slow:
            await self.script.release.wait()
        if self.address in self.script.dead:
            raise TimeoutError("no answer")
        self._up = True

    async def write(self, data: bytes) -> None:
        if self.script.write_failures:
            self.script.write_failures -= 1
            if not self.script.stuck_connected:
                self._up = False
            raise self.script.write_error
        self.script.sent.setdefault(self.address, []).append(bytes(data).hex().upper())

    async def disconnect(self) -> None:
        self.disconnected = True
        self._up = False
        if self.address in self.script.disconnect_raises:
            raise OSError("already gone")

    @property
    def connected(self) -> bool:
        return self._up


class RecordedSleep:
    """Stands in for the retry delay and the identify pause: records each wait, returns at once
    unless the test holds the gate shut."""

    def __init__(self) -> None:
        self.delays: list[float] = []
        self.gate = asyncio.Event()
        self.gate.set()
        self.on_wait = None

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)
        if self.on_wait:
            self.on_wait(len(self.delays))
        await self.gate.wait()
        await asyncio.sleep(0)


async def until(check, turns: int = 500) -> None:
    """Let the event loop run until ``check()`` holds. Counts loop turns, never seconds."""
    for _ in range(turns):
        if check():
            return
        await asyncio.sleep(0)
    raise AssertionError("the driver never got there")


@pytest_asyncio.fixture
async def rig():
    script, sleep, made = Scripted(), RecordedSleep(), []

    def build(**kwargs) -> YongnuoDriver:
        built = YongnuoDriver(transport_factory=script, sleep=sleep, **kwargs)
        made.append(built)
        return built

    yield script, sleep, build
    for built in made:
        await built.stop()


def lit(brightness: float = 50, kelvin: int = 5600) -> LightState:
    return LightState(brightness=brightness, cct=Cct(kelvin=kelvin))


async def test_a_failed_send_is_tried_again_after_the_project_backoff(rig):
    script, sleep, build = rig
    driver = build()
    yn = light("YNLUX100PRO", 7)
    script.write_failures = 2
    driver.apply(yn, lit(91.6, 3300))
    await until(lambda: script.bytes_for(yn.address))
    assert script.bytes_for(yn.address) == ["AE0309070CE45BA006"]  # the user's final value, not lost
    assert sleep.delays == [retry_delay(1), retry_delay(2)] == [2.0, 4.0]


async def test_a_dead_light_does_not_hold_up_a_healthy_one_and_is_not_retried_in_a_loop(rig):
    script, sleep, build = rig
    driver = build()
    dead, fine = light("YN150", 1), light("YNLUX100PRO", 2)
    script.dead.add(dead.address)
    sleep.gate.clear()  # the dead light waits out its delay for the whole test
    driver.apply(dead, lit())
    driver.apply(fine, lit(100, 5600))
    await until(lambda: script.bytes_for(fine.address))
    assert script.bytes_for(fine.address) == ["AE030902" "15E0" "64A000"]
    for _ in range(100):  # time passes with no new input for the dead light
        await asyncio.sleep(0)
    assert script.connect_attempts[dead.address] == 1  # one try, then it waited
    assert sleep.delays == [2.0]


async def test_new_input_ends_the_back_off_and_is_tried_at_once(rig):
    script, sleep, build = rig
    driver = build()
    yn = light("YNLUX100PRO", 7)
    script.dead.add(yn.address)
    sleep.gate.clear()  # the delay would never end on its own
    driver.apply(yn, lit(50, 3300))
    await until(lambda: sleep.delays)  # failed once, now waiting
    script.dead.clear()  # the phone app let go; the user moves the fader
    driver.apply(yn, lit(91.6, 3300))
    await until(lambda: script.bytes_for(yn.address))
    assert script.bytes_for(yn.address) == ["AE0309070CE45BA006"]
    assert driver.status(yn)["reachable"] is True


async def test_a_value_error_from_the_link_is_retried_not_dropped_as_a_bad_state(rig):
    script, sleep, build = rig
    driver = build()
    yn = light("YNLUX100PRO", 7)
    script.write_failures = 1
    script.write_error = ValueError("closed")
    driver.apply(yn, lit(91.6, 3300))
    await until(lambda: script.bytes_for(yn.address))
    assert script.bytes_for(yn.address) == ["AE0309070CE45BA006"]


async def test_a_hung_connect_to_one_light_does_not_stop_another(rig):
    script, sleep, build = rig
    driver = build()
    stuck, fine = light("YN150", 1), light("YNLUX100PRO", 2)
    script.hung.add(stuck.address)
    driver.apply(stuck, lit())
    driver.apply(fine, lit(100, 5600))
    await until(lambda: script.bytes_for(fine.address))


async def test_status_says_unreachable_when_a_write_failed_even_if_the_link_still_claims_to_be_up(rig):
    script, sleep, build = rig
    driver = build()
    yn = light("YN150", 4)
    driver.apply(yn, lit())
    await driver.flush()
    assert driver.status(yn)["reachable"] is True
    script.stuck_connected = True
    script.write_failures = 1
    sleep.gate.clear()
    driver.apply(yn, lit(80))
    await until(lambda: sleep.delays)
    assert driver.status(yn)["reachable"] is False
    sleep.gate.set()  # the retry must build a fresh link, not reuse the broken one
    await until(lambda: len(script.bytes_for(yn.address)) == 3)
    assert len(script.made) == 2 and script.made[0].disconnected
    assert driver.status(yn)["reachable"] is True


async def test_two_connects_to_one_light_make_one_link(rig):
    script, sleep, build = rig
    driver = build()
    yn = light("YN150", 4)
    await asyncio.gather(driver.connect(yn), driver.connect(yn))
    assert len(script.made) == 1


async def test_stop_disconnects_every_light_even_when_one_will_not_let_go(rig):
    script, sleep, build = rig
    driver = build()
    lights = [light("YN150", n) for n in (1, 2, 3)]
    for l in lights:
        await driver.connect(l)
    script.disconnect_raises.add(lights[0].address)
    await driver.stop()
    assert [t.disconnected for t in script.made] == [True, True, True]


async def test_a_light_that_is_not_a_yongnuo_model_is_refused_in_plain_words(rig):
    script, sleep, build = rig
    stray = light("GODOX-X", 1)
    with pytest.raises(ValueError, match="not a Yongnuo model"):
        build().apply(stray, lit())


async def test_a_connect_that_never_answers_times_out_into_the_back_off_and_flush_returns(rig):
    script, sleep, build = rig
    driver = build(connect_timeout=0.01)
    stuck = light("YN150", 1)
    script.hung.add(stuck.address)
    sleep.gate.clear()
    driver.apply(stuck, lit())
    await asyncio.wait_for(driver.flush(), 5)  # without a bound on connect this waits for ever
    assert sleep.delays == [2.0]
    assert driver.status(stuck) == {"reachable": False, "held": True}
    await asyncio.wait_for(driver.flush(), 5)  # and with nothing queued it returns at once


async def test_a_failed_connect_does_not_leave_its_link_half_open(rig):
    script, sleep, build = rig
    driver = build()
    yn = light("YN150", 1)
    script.dead.add(yn.address)
    with pytest.raises(TimeoutError):
        await driver.connect(yn)
    assert [t.disconnected for t in script.made] == [True]


async def test_identify_that_breaks_off_mid_pulse_puts_the_light_back(rig):
    script, sleep, build = rig
    driver = build()
    yn = light("YNLUX100PRO", 7)
    driver.apply(yn, lit(30, 3300))
    await driver.flush()
    sleep.on_wait = lambda n: setattr(script, "write_failures", 1) if n == 1 else None
    with pytest.raises(OSError):
        await driver.identify(yn)
    await until(lambda: script.bytes_for(yn.address)[-1] == "AE030907" "0CE4" "1EA000")  # back to 30 %
    assert script.bytes_for(yn.address)[1] == "AE030907" "0CE4" "64A000"  # the pulse did start


async def test_stop_while_identify_is_mid_pulse_leaves_no_link_open(rig):
    script, sleep, build = rig
    driver = build()
    yn = light("YNLUX100PRO", 7)
    driver.apply(yn, lit(30, 3300))
    await driver.flush()
    sleep.gate.clear()
    pulse = asyncio.ensure_future(driver.identify(yn))
    await until(lambda: sleep.delays)  # the pulse is holding the light, waiting between frames
    await driver.stop()
    sleep.gate.set()
    with pytest.raises(ConnectionAbortedError):
        await pulse
    assert len(script.made) == 1 and not script.made[0].connected


async def test_stop_while_a_connect_is_in_flight_releases_the_link_it_opens(rig):
    script, sleep, build = rig
    driver = build()
    yn = light("YN150", 4)
    script.slow.add(yn.address)
    opening = asyncio.ensure_future(driver.connect(yn))
    await until(lambda: script.made)
    await driver.stop()
    script.release.set()
    with pytest.raises(ConnectionAbortedError):
        await opening
    assert not any(t.connected for t in script.made)
    assert driver.status(yn)["reachable"] is None


async def test_stop_forgets_what_it_knew_so_a_restarted_light_is_switched_on_again(rig):
    script, sleep, build = rig
    driver = build()
    yn = light("YN150", 21)
    driver.apply(yn, lit(90, 5300))
    await driver.flush()
    await driver.stop()
    await driver.start()
    driver.apply(yn, lit(90, 5300))
    await driver.flush()
    assert script.bytes_for(yn.address).count("AE0106150156") == 2  # power-on sent again after the restart


async def test_identify_wakes_a_plain_light_that_is_off_and_puts_it_back_off(rig):
    script, sleep, build = rig
    driver = build()
    yn = light("YN150", 21)
    driver.apply(yn, LightState(power=False))
    await driver.flush()
    await driver.identify(yn)
    assert script.bytes_for(yn.address) == [
        "AE0106150056",  # off
        "AE0106150156",  # identify switches it on first, or the pulse is invisible
        "AE030815" "15E0" "6456",
        "AE030815" "15E0" "0A56",
        "AE030815" "15E0" "6456",
        "AE0106150056",  # and puts it back off
    ]


async def test_a_fader_move_during_identify_is_not_overwritten_by_the_restore(rig):
    script, sleep, build = rig
    driver = build()
    yn = light("YNLUX100PRO", 7)
    driver.apply(yn, lit(80, 3300))
    await driver.flush()
    sleep.on_wait = lambda n: driver.apply(yn, lit(20, 3300)) if n == 1 else None
    await driver.identify(yn)
    await until(lambda: script.bytes_for(yn.address)[-1] == "AE030907" "0CE4" "14A000")
    assert script.bytes_for(yn.address).count("AE030907" "0CE4" "50A000") == 1  # the old 80 % was sent once, before the pulse
