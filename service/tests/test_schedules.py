"""SPEC-013 acceptance tests: schedules fire looks and all-off on a fake clock, through the running app.

The clock is a fake that the test moves; the service reads it on a 20 ms tick, so nothing waits on
the wall clock. The app runs in demo mode (no Bluetooth) and is reached as the Mac shell reaches it.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from gaffer.app import create_app
from gaffer.session import COOKIE, protect

SECRET = "test-secret-for-schedules"
WS = "ws://127.0.0.1/ws"

MONDAY_2159 = datetime(2026, 10, 19, 21, 59, 20)  # 19 Oct 2026 is a Monday
MONDAY_2200 = datetime(2026, 10, 19, 22, 0, 20)
SATURDAY_2200 = datetime(2026, 10, 24, 22, 0, 20)
TUESDAY_0200 = datetime(2026, 10, 20, 2, 0, 20)


class FakeClock:
    """The wall clock the schedules read. Counts reads so a test can wait for the scheduler to have looked."""

    def __init__(self, now: datetime) -> None:
        self.now = now
        self.reads = 0

    def __call__(self) -> datetime:
        self.reads += 1
        return self.now

    def set(self, now: datetime) -> None:
        """Move the clock, then wait until the scheduler has read it a few times (so a firing would have happened)."""
        self.now = now
        seen = self.reads
        _wait(lambda: self.reads >= seen + 3, "the scheduler reading the new time")


def _wait(predicate, what, seconds=5.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError(f"never happened: {what}")


@pytest.fixture
def studio(tmp_path):
    clock = FakeClock(MONDAY_2159)
    app = create_app(demo=True, data_dir=tmp_path, clock=clock, schedule_interval=0.02)
    with TestClient(protect(app, SECRET), base_url="http://127.0.0.1", cookies={COOKIE: SECRET}) as client:
        client.clock = clock  # type: ignore[attr-defined]
        client.hub = app.state.hub  # type: ignore[attr-defined]
        yield client


def _lights(client):
    return {light["name"]: light for light in client.get("/api/lights").json()["lights"]}


def _ran(hub):
    return [e for e in hub.log if e["kind"] == "schedule"]


def _failed(hub):
    return [e for e in hub.log if e["kind"] == "error"]


def _delete_look(client, look_id):
    with client.websocket_connect(WS) as ws:
        ws.receive_json()  # hello
        ws.send_json({"type": "looks.delete", "id": look_id})
        while (m := ws.receive_json()).get("type") != "store" or m.get("collection") != "looks":
            pass


def _error_toast_when_the_clock_reaches(client, when):
    """Move the clock with a window connected, and return the error toast that window is shown (fails after 5 s)."""
    toasts: list[str] = []

    def read(ws):
        try:
            while True:
                message = ws.receive_json()
                if message.get("type") == "toast" and message.get("kind") == "error":
                    toasts.append(message["text"])
                    return
        except Exception:  # noqa: BLE001 - the socket closing at the end of the test ends the reader
            return

    with client.websocket_connect(WS) as ws:
        ws.receive_json()  # hello
        threading.Thread(target=read, args=(ws,), daemon=True).start()
        client.clock.set(when)
        _wait(lambda: toasts, "an error toast reaching the window")
    return toasts[0]


def _save_schedule(client, schedule):
    """schedules.save over the socket, as the window's editor sends it. Returns the reply."""
    with client.websocket_connect(WS) as ws:
        ws.receive_json()  # hello
        ws.send_json({"type": "schedules.save", "schedule": schedule, "rid": 1})
        while (reply := ws.receive_json()).get("rid") != 1:
            pass
        return reply


def test_ac5_moody_at_22_00_mon_to_fri_fires_the_look_and_not_saturday_or_one_minute_early(studio):
    key = _lights(studio)["Key light"]
    moody = studio.post("/api/looks", json={
        "name": "Moody", "fade_seconds": 0,
        "lights": {key["id"]: {"power": True, "brightness": 17.0}}}).json()["look"]["id"]
    assert _lights(studio)["Key light"]["state"]["brightness"] != 17.0
    reply = _save_schedule(studio, {"name": "Moody at night", "at": "22:00", "days": [0, 1, 2, 3, 4],
                                    "action": "look", "target": moody})
    assert reply["type"] == "ack", reply

    # Monday 21:59: not yet. Saturday 22:00: wrong day. Nothing has moved after either.
    studio.clock.set(MONDAY_2159)
    studio.clock.set(SATURDAY_2200)
    assert studio.hub.look is None
    assert _lights(studio)["Key light"]["state"]["brightness"] != 17.0

    # Monday 22:00: the look is applied and the light shows its values.
    studio.clock.set(MONDAY_2200)
    _wait(lambda: _lights(studio)["Key light"]["state"]["brightness"] == 17.0, "the light showing Moody's values")
    assert studio.hub.look == {"id": moody, "name": "Moody"}

    # The same minute does not fire twice: the clock has been read many times at 22:00 and the look ran once.
    assert len(_ran(studio.hub)) == 1
    # "off" turns every light off at its own time.
    _save_schedule(studio, {"name": "Lights out", "at": "02:00", "days": [1], "action": "off"})
    assert any(light["state"]["power"] for light in _lights(studio).values())
    studio.clock.set(TUESDAY_0200)
    _wait(lambda: not any(light["state"]["power"] for light in _lights(studio).values()), "every light off")
    assert studio.hub.look is None


def test_a_schedule_that_is_not_valid_is_refused_and_stores_nothing(studio):
    good = {"name": "x", "at": "22:00", "days": [0], "action": "off"}
    for bad in ({**good, "name": " "}, {**good, "at": "25:00"}, {**good, "at": "9:5"}, {**good, "days": []},
                {**good, "days": [7]}, {**good, "days": [0, 0]}, {**good, "action": "sunrise"},
                {**good, "action": "look", "target": "no-such-look"}, {**good, "action": "look"},
                {**good, "id": "constructor"}, {**good, "name": "x" * 81}, {**good, "at": "09:3０"}):
        reply = _save_schedule(studio, bad)
        assert reply["type"] == "error", bad
        assert not any(p in reply["text"] for p in ("/Users/", "/private/", "/var/")), reply
    assert studio.hub.store.items("schedules") == []
    assert _save_schedule(studio, good)["type"] == "ack"


def test_a_schedule_whose_look_was_deleted_can_still_be_paused_and_keeps_its_creation_time(studio):
    key = _lights(studio)["Key light"]
    moody = studio.post("/api/looks", json={"name": "Moody", "fade_seconds": 0, "lights": {key["id"]: {"power": True}}}).json()["look"]["id"]
    saved = _save_schedule(studio, {"name": "Moody at night", "at": "22:00", "days": [0], "action": "look", "target": moody})["schedule"]
    _delete_look(studio, moody)

    paused = _save_schedule(studio, {**saved, "enabled": False})
    assert paused["type"] == "ack", paused
    assert paused["schedule"]["enabled"] is False
    assert paused["schedule"]["created"] == saved["created"]
    assert _save_schedule(studio, {**saved, "enabled": True})["type"] == "error"  # turning it on needs the look


def test_a_schedule_whose_look_was_deleted_says_it_did_not_run(studio):
    key = _lights(studio)["Key light"]
    moody = studio.post("/api/looks", json={"name": "Moody", "fade_seconds": 0, "lights": {key["id"]: {"power": True}}}).json()["look"]["id"]
    _save_schedule(studio, {"name": "Moody at night", "at": "22:00", "days": [0], "action": "look", "target": moody})
    _delete_look(studio, moody)

    assert "Moody at night" in _error_toast_when_the_clock_reaches(studio, MONDAY_2200)
    assert "Moody at night" in _failed(studio.hub)[0]["text"]
    assert _ran(studio.hub) == []


def test_an_all_off_schedule_that_fails_says_so_and_does_not_claim_it_ran(studio):
    async def broken(on):
        raise RuntimeError("the driver fell over")

    studio.hub.power_all = broken  # the lights cannot be reached
    _save_schedule(studio, {"name": "Lights out", "at": "22:00", "days": [0], "action": "off"})

    assert "Lights out" in _error_toast_when_the_clock_reaches(studio, MONDAY_2200)
    assert "Lights out" in _failed(studio.hub)[0]["text"]
    assert _ran(studio.hub) == []
