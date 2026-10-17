"""SPEC-008, adding a light: scan by model, flash it, name it, and say when an official app holds it.

The first three tests drive the demo service through its WebSocket and ``GET /api/lights``. The fourth
gives the hub the real Zhiyun and Yongnuo drivers with fake transports, so a flash is seen to reach the
right brand with commands that driver already sends. Nothing opens Bluetooth.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from gaffer import demo
from gaffer.app import create_app
from gaffer.drivers import DriverContext
from gaffer.drivers.yongnuo import YongnuoDriver
from gaffer.drivers.zhiyun import ZhiyunDriver, protocol as zy
from gaffer.hub import Client, Hub
from gaffer.lights import LightLibrary
from gaffer.store import Store


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "PACE", 0.05)
    with TestClient(create_app(demo=True, data_dir=tmp_path)) as c:
        yield c


def _until(ws, predicate, limit=400):
    for _ in range(limit):
        message = ws.receive_json()
        if predicate(message):
            return message
    raise AssertionError("expected message never arrived")


def _ack(of):
    return lambda m: m["type"] == "ack" and m["of"] == of


def _scan(ws):
    ws.send_json({"type": "lights.scan", "seconds": 2, "rid": 1})
    return _until(ws, _ack("lights.scan"))["nearby"]


def _lights(client):
    return client.get("/api/lights").json()["lights"]


def test_the_add_flow_lists_a_light_per_brand_flashes_the_chosen_one_and_names_it(client):
    with client.websocket_connect("/ws") as ws:
        assert _until(ws, lambda m: m["type"] == "hello")
        found = _scan(ws)
        addable = {(n["brand"], n["model"]) for n in found if n["relation"] in ("unpaired", "new")}
        assert addable == {("Godox", "TL60"), ("Zhiyun", "MOLUS G200 (demo)"), ("Yongnuo", "YN150Li (demo)")}

        zhiyun = next(n for n in found if n["brand"] == "Zhiyun")
        ws.send_json({"type": "lights.add", "address": zhiyun["address"], "rid": 2})
        light = _until(ws, _ack("lights.add"))["light"]

        ws.send_json({"type": "lights.identify", "light": light, "rid": 3})
        assert _until(ws, _ack("lights.identify"))["driver"] == "demo"  # the Zhiyun stand-in's own driver
        assert client.app.state.hub.registry.get("demo").identified == [light]

        ws.send_json({"type": "lights.rename", "light": light, "name": "Window"})
        _until(ws, lambda m: m["type"] == "lights" and any(l["name"] == "Window" for l in m["lights"]))
    assert [l["model"] for l in _lights(client) if l["name"] == "Window"] == ["MOLUS G200 (demo)"]


def test_a_yongnuo_light_cannot_be_saved_without_a_channel(client):
    before = len(_lights(client))
    with client.websocket_connect("/ws") as ws:
        _until(ws, lambda m: m["type"] == "hello")
        yongnuo = next(n for n in _scan(ws) if n["brand"] == "Yongnuo")
        assert yongnuo["needs_channel"] is True
        for channel in (None, "", 256, True):
            ws.send_json({"type": "lights.add", "address": yongnuo["address"], "rid": 2, **({} if channel is None else {"channel": channel})})
            assert "channel" in _until(ws, lambda m: m.get("rid") == 2)["text"].lower()
            assert len(_lights(client)) == before  # a refused request saves nothing
        ws.send_json({"type": "lights.add", "address": yongnuo["address"], "channel": 5, "rid": 3})
        light = _until(ws, _ack("lights.add"))["light"]
    saved = next(l for l in _lights(client) if l["id"] == light)
    assert saved["channel"] == 5 and saved["model"] == "YN150Li (demo)"


def test_a_light_held_by_an_official_app_is_reported_and_clears(client):
    with client.websocket_connect("/ws") as ws:
        _until(ws, lambda m: m["type"] == "hello")
        panel = next(l["id"] for l in _lights(client) if l["name"] == "Zhiyun panel")
        assert {l["held"] for l in _lights(client)} == {False}
        ws.send_json({"type": "demo.held", "light": panel, "held": True})
        pushed = _until(ws, lambda m: m["type"] == "lights")["lights"]  # the page is told at once, not a second later
        assert [l["id"] for l in pushed if l["held"]] == [panel]
        held = [l for l in _lights(client) if l["held"]]
        assert [(l["id"], l["caps"]["brand"]) for l in held] == [(panel, "Zhiyun")]
        ws.send_json({"type": "demo.held", "light": panel, "held": False})
        assert not any(l["held"] for l in _until(ws, lambda m: m["type"] == "lights")["lights"])
    assert {l["held"] for l in _lights(client)} == {False}


# -- the real drivers behind the hub ---------------------------------------------------------------------


class RecordingLink:
    connected = True

    def __init__(self, writes):
        self.writes = writes

    async def write(self, data):
        self.writes.append(bytes(data))

    async def close(self):
        self.connected = False


class ZhiyunWire:
    def __init__(self):
        self.writes = []

    async def open(self, address, on_notify, on_lost):
        return RecordingLink(self.writes)


class YongnuoWire:
    sent = []

    def __init__(self, address):
        self._up = False

    async def connect(self):
        self._up = True

    async def write(self, data):
        YongnuoWire.sent.append(bytes(data))

    async def disconnect(self):
        self._up = False

    @property
    def connected(self):
        return self._up


class HeardScanner:
    """A scan that hears one Zhiyun and one Yongnuo light, the way bleak hands adverts over."""

    devices = {}
    busy = False

    async def scan(self, seconds, on_found=None, on_other=None):
        for address, name in (("00000000-0000-0000-0000-0000000000a1", "PL109_C75E"),
                              ("00000000-0000-0000-0000-0000000000a2", "YN150Li")):
            on_other(SimpleNamespace(address=address, name=name),
                     SimpleNamespace(local_name=name, rssi=-60, service_uuids=[], manufacturer_data={}))
        return []


async def _nosleep(_seconds):
    return None


async def test_flashing_a_scanned_light_reaches_its_own_driver_with_commands_that_driver_already_sends(tmp_path):
    YongnuoWire.sent = []
    zhiyun_wire = ZhiyunWire()
    hub = Hub(Store(tmp_path), LightLibrary(tmp_path), demo=False, scanner=HeardScanner())
    zhiyun = hub.registry.drivers["zhiyun"] = ZhiyunDriver(DriverContext(), transport=zhiyun_wire, sleep=_nosleep)
    yongnuo = hub.registry.drivers["yongnuo"] = YongnuoDriver(DriverContext(), transport_factory=YongnuoWire, sleep=_nosleep)
    try:
        listed = {n["brand"]: n for n in await hub.scan(2)}
        assert (listed["Zhiyun"]["model"], listed["Yongnuo"]["model"]) == ("MOLUS G200", "YN150")
        client = Client()
        zy_light = await hub.add_light(client, listed["Zhiyun"]["address"], "Key")
        yn_light = await hub.add_light(client, listed["Yongnuo"]["address"], "Fill", 5)

        assert await hub.identify(zy_light.id) == "zhiyun"
        commands = {zy.parse_frame(w).command for w in zhiyun_wire.writes[5:]}  # after the five handshake frames
        assert zy.Command.SET_BRIGHTNESS in commands and 0x1101 not in commands
        assert YongnuoWire.sent == []  # Yongnuo's wire heard nothing of it

        assert await hub.identify(yn_light.id) == "yongnuo"
        assert YongnuoWire.sent and all(frame[3] == 5 for frame in YongnuoWire.sent)  # every frame carries channel 5
        assert any(frame.hex().upper().endswith("6456") for frame in YongnuoWire.sent)  # full brightness, plain frame
    finally:
        await zhiyun.stop()
        await yongnuo.stop()
