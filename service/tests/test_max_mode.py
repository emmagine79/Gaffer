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


def test_a_slow_max_mode_write_does_not_hold_up_the_next_command(tmp_path, monkeypatch):
    """A Max Mode write to a light that is slow to answer must not freeze the rest of the page."""
    import asyncio

    monkeypatch.setattr(demo, "PACE", 0.05)

    class SlowWire(Wire):
        async def open(self, address, on_notify, on_lost):
            writes = self.writes

            class SlowLink(Link):
                async def write(self, data):
                    if zy.parse_frame(bytes(data)).command == zy.Command.MAX_MODE:
                        await asyncio.sleep(1.0)  # a light out of range takes this long or longer
                    writes.append(bytes(data))

            return SlowLink(writes)

    wire = SlowWire()
    app = create_app(demo=True, data_dir=tmp_path)
    app.state.hub.registry.drivers["zhiyun"] = ZhiyunDriver(DriverContext(), transport=wire, sleep=_nosleep)
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        _until(ws, lambda m: m["type"] == "hello")
        light = _molus(client, ws, wire)
        key = _light(client, "Key light")["id"]
        ws.send_json({"type": "light.max_mode", "light": light, "on": True, "rid": 1})
        ws.send_json({"type": "light.max_mode", "light": key, "on": True, "rid": 2})  # refused at once
        first = _until(ws, lambda m: m.get("rid") in (1, 2))
        assert first["rid"] == 2, "the second command waited behind the slow Max Mode write"
        assert _until(ws, lambda m: m.get("rid") == 1)["type"] == "ack"


def _answer(command: int, payload: bytes, sequence: int) -> bytes:
    """A frame as the G200 sends it: direction 01 00, sequence, command, payload, CRC by binascii."""
    import binascii
    import struct

    body = b"\x01\x00" + struct.pack("<HH", sequence, command) + payload
    return b"\x24\x3c" + struct.pack("<H", len(body)) + body + struct.pack("<H", binascii.crc_hqx(body, 0))


def test_max_mode_switched_on_at_the_light_shows_in_gaffer_at_full_brightness(tmp_path, monkeypatch):
    """Captain, 18 Oct: Gaffer at 26%, Max pressed on the G200 itself; Gaffer kept showing 26% and Max off."""
    from gaffer import hub as hub_module

    monkeypatch.setattr(demo, "PACE", 0.05)
    monkeypatch.setattr(hub_module, "SETTLE_SECONDS", 0.0)
    unit = {"max": False}

    class G200(Wire):
        """Answers Max Mode reads the way the real light did in the 18 Oct capture."""

        async def open(self, address, on_notify, on_lost):
            writes = self.writes

            class AnsweringLink(Link):
                async def write(self, data):
                    writes.append(bytes(data))
                    frame = zy.parse_frame(bytes(data))
                    if frame.command == zy.Command.MAX_MODE and frame.payload == bytes.fromhex("03800000"):
                        on_notify(_answer(zy.Command.MAX_MODE, bytes.fromhex("038000") + bytes([unit["max"]]), frame.sequence))

            return AnsweringLink(writes)

    wire = G200()
    app = create_app(demo=True, data_dir=tmp_path)
    app.state.hub.store.update_settings({"sync_interval": 0.05})
    app.state.hub.registry.drivers["zhiyun"] = ZhiyunDriver(DriverContext(), transport=wire, sleep=_nosleep)
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        _until(ws, lambda m: m["type"] == "hello")
        light = _molus(client, ws, wire)
        ws.send_json({"type": "set", "light": light, "patch": {"brightness": 26}})
        _wait(lambda: _light(client, "Zhiyun panel")["state"]["brightness"] == 26, "Gaffer at 26%")

        unit["max"] = True  # Captain holds MODE and CCT on the light
        _wait(lambda: _light(client, "Zhiyun panel")["max_mode"] is True, "Max Mode to show as on")
        assert _light(client, "Zhiyun panel")["state"]["brightness"] == 100

        unit["max"] = False  # and switches it off again on the light
        _wait(lambda: _light(client, "Zhiyun panel")["max_mode"] is False, "Max Mode to show as off")
