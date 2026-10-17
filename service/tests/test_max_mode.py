"""Max Mode (turbo) for the Zhiyun MOLUS G200, through the service's own WebSocket.

The hub gets the real Zhiyun driver with a fake transport, so the frames a command produces are the
frames a light would receive. Nothing opens Bluetooth. The expected frames were worked out from the
frame rules in drivers/zhiyun/protocol.py (header 24 3C, length, body, CRC-16/XMODEM), with the CRC
checked by binascii.crc_hqx and not by the code under test.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from gaffer import demo
from gaffer.app import create_app
from gaffer.drivers import DriverContext
from gaffer.drivers.zhiyun import ZhiyunDriver, protocol as zy

#: Sequence numbers 0-4 are the handshake. The light's first state is power (5), colour temperature (6)
#: and brightness (7), so the first Max Mode write is number 8 and the next is 9. Op byte 01, as
#: PL109.json's control_mode says. Value byte: 01 on, 00 off.
HANDSHAKE_FRAMES = 5
FIRST_STATE_FRAMES = 3
MAX_ON_FRAME = "243c0a0000010800091003800101d73a"
MAX_OFF_FRAME = "243c0a0000010900091003800100256d"


class Link:
    connected = True

    def __init__(self, writes):
        self.writes = writes

    async def write(self, data):
        self.writes.append(bytes(data))

    async def close(self):
        self.connected = False


class Wire:
    """The fake Zhiyun transport: records every frame written."""

    def __init__(self):
        self.writes = []

    async def open(self, address, on_notify, on_lost):
        return Link(self.writes)


async def _nosleep(_seconds):
    return None


@pytest.fixture
def studio(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "PACE", 0.05)
    wire = Wire()
    app = create_app(demo=True, data_dir=tmp_path)
    app.state.hub.registry.drivers["zhiyun"] = ZhiyunDriver(DriverContext(), transport=wire, sleep=_nosleep)
    with TestClient(app) as client:
        yield client, wire


def _until(ws, predicate, limit=400):
    for _ in range(limit):
        message = ws.receive_json()
        if predicate(message):
            return message
    raise AssertionError("expected message never arrived")


def _wait(condition, what, seconds=5.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError(f"timed out waiting for {what}")


def _light(client, name):
    return next(l for l in client.get("/api/lights").json()["lights"] if l["name"] == name)


def _ask(ws, message, rid):
    ws.send_json({**message, "rid": rid})
    return _until(ws, lambda m: m.get("rid") == rid)


def _molus(client, ws, wire):
    """The demo's Zhiyun panel, moved onto the real MOLUS G200 model, so the real Zhiyun driver takes it."""
    light = _light(client, "Zhiyun panel")["id"]
    ws.send_json({"type": "lights.model", "light": light, "radio_id": "PL109"})
    _wait(lambda: len(wire.writes) >= HANDSHAKE_FRAMES + FIRST_STATE_FRAMES, "the light's handshake and first state")
    return light


def _max_mode_frames(wire):
    return [w.hex() for w in wire.writes[HANDSHAKE_FRAMES:] if zy.parse_frame(w).command == zy.Command.MAX_MODE]


def test_light_max_mode_sends_the_1009_frame_for_on_and_for_off(studio):
    client, wire = studio
    with client.websocket_connect("/ws") as ws:
        _until(ws, lambda m: m["type"] == "hello")
        light = _molus(client, ws, wire)

        assert _ask(ws, {"type": "light.max_mode", "light": light, "on": True}, 1)["type"] == "ack"
        assert _max_mode_frames(wire) == [MAX_ON_FRAME]
        assert _light(client, "Zhiyun panel")["max_mode"] is True

        assert _ask(ws, {"type": "light.max_mode", "light": light, "on": False}, 2)["type"] == "ack"
        assert _max_mode_frames(wire) == [MAX_ON_FRAME, MAX_OFF_FRAME]
        assert _light(client, "Zhiyun panel")["max_mode"] is False


def test_light_max_mode_is_refused_for_a_model_without_the_flag_and_for_a_value_that_is_not_a_boolean(studio):
    client, wire = studio
    with client.websocket_connect("/ws") as ws:
        _until(ws, lambda m: m["type"] == "hello")
        light = _molus(client, ws, wire)
        key = _light(client, "Key light")
        assert key["max_mode"] is None and key["caps"]["max_mode"] is False

        refused = _ask(ws, {"type": "light.max_mode", "light": key["id"], "on": True}, 1)
        assert refused["type"] == "error" and refused["text"] == "Key light has no Max Mode."

        refused = _ask(ws, {"type": "light.max_mode", "light": light, "on": "yes"}, 2)
        assert refused["type"] == "error" and refused["text"] == "on must be true or false"
        assert _max_mode_frames(wire) == []


def test_a_light_that_is_off_refuses_max_mode_and_switching_it_off_resets_the_value(studio):
    client, wire = studio
    with client.websocket_connect("/ws") as ws:
        _until(ws, lambda m: m["type"] == "hello")
        light = _molus(client, ws, wire)
        assert _ask(ws, {"type": "light.max_mode", "light": light, "on": True}, 1)["type"] == "ack"
        assert _light(client, "Zhiyun panel")["max_mode"] is True

        ws.send_json({"type": "power", "light": light, "on": False})
        _wait(lambda: _light(client, "Zhiyun panel")["max_mode"] is False, "Max Mode to reset at power-off")
        last = zy.parse_frame(wire.writes[-1])
        assert (last.command, last.payload[-1]) == (zy.Command.POWER_STATE, 0)  # the power-off write, value byte 00

        refused = _ask(ws, {"type": "light.max_mode", "light": light, "on": True}, 2)
        assert refused["type"] == "error" and refused["text"] == "Switch the light on first."
        assert _max_mode_frames(wire) == [MAX_ON_FRAME]
