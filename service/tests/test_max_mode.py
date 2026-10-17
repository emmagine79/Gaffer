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
#: and brightness (7), so the first Max Mode write is number 8. Gaffer then sends its own colour temperature
#: back over the light's Max Mode 4300 K (9), so the Max off write is number 10. Op byte 01, as PL109.json's
#: control_mode says. Value byte: 01 on, 00 off.
HANDSHAKE_FRAMES = 5
FIRST_STATE_FRAMES = 3
MAX_ON_FRAME = "243c0a0000010800091003800101d73a"
MAX_OFF_FRAME = "243c0a0000010a0009100380010050a5"


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
    app.state.hub.registry.drivers["zhiyun"] = ZhiyunDriver(DriverContext(), transport=wire, sleep=_nosleep, reply_timeout=0)
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
    """The Max Mode writes, leaving out the reads the hub sends to notice a press on the light."""
    return [
        w.hex()
        for w in wire.writes[HANDSHAKE_FRAMES:]
        if zy.parse_frame(w).command == zy.Command.MAX_MODE and zy.parse_frame(w).payload != zy.encode_query()
    ]


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
    app.state.hub.registry.drivers["zhiyun"] = ZhiyunDriver(DriverContext(), transport=wire, sleep=_nosleep, reply_timeout=0)
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
            self.on_lost = on_lost

            class AnsweringLink(Link):
                async def write(self, data):
                    writes.append(bytes(data))
                    frame = zy.parse_frame(bytes(data))
                    if frame.command == zy.Command.MAX_MODE and frame.payload == bytes.fromhex("03800000"):
                        on_notify(_answer(zy.Command.MAX_MODE, bytes.fromhex("038000") + bytes([unit["max"]]), frame.sequence))

            self.link = AnsweringLink(writes)
            return self.link

    wire = G200()
    app = create_app(demo=True, data_dir=tmp_path)
    app.state.hub.store.update_settings({"sync_interval": 0.05})
    app.state.hub.registry.drivers["zhiyun"] = ZhiyunDriver(
        DriverContext(), transport=wire, sleep=_nosleep, backoff_sleep=_nosleep
    , reply_timeout=0)
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        _until(ws, lambda m: m["type"] == "hello")
        light = _molus(client, ws, wire)
        ws.send_json({"type": "set", "light": light, "patch": {"brightness": 26}})
        _wait(lambda: _light(client, "Zhiyun panel")["state"]["brightness"] == 26, "Gaffer at 26%")

        unit["max"] = True  # Captain holds MODE and CCT on the light
        _wait(lambda: _light(client, "Zhiyun panel")["max_mode"] is True, "Max Mode to show as on")
        assert _light(client, "Zhiyun panel")["state"]["brightness"] == 100
        assert _light(client, "Zhiyun panel")["state"]["cct"]["kelvin"] == 4300  # the light's own Max Mode kelvin

        # The link drops and comes back: Gaffer re-sends what it wants, which must be 100, not the old 26.
        before = len(wire.writes)
        wire.link.connected = False
        client.portal.call(wire.on_lost)  # on the service's own event loop, as bleak calls it
        _wait(lambda: any(zy.parse_frame(w).command == zy.Command.SET_BRIGHTNESS for w in wire.writes[before:]),
              "the state to be sent again after the link came back")
        resent = [zy.parse_frame(w) for w in wire.writes[before:] if zy.parse_frame(w).command == zy.Command.SET_BRIGHTNESS]
        assert zy.decode_brightness_response(resent[-1].payload) == 100.0

        unit["max"] = False  # and switches it off again on the light
        _wait(lambda: _light(client, "Zhiyun panel")["max_mode"] is False, "Max Mode to show as off")


def test_a_slider_move_while_the_light_answers_is_not_overwritten_by_max_mode(tmp_path, monkeypatch):
    """Review round 2: the light's 'Max on' answer must not put 100% over a level set while it was asked."""
    from gaffer import hub as hub_module

    monkeypatch.setattr(demo, "PACE", 0.05)
    monkeypatch.setattr(hub_module, "SETTLE_SECONDS", 0.0)
    held: list = []

    class SlowG200(Wire):
        """Says Max Mode is on, but only when the test lets the answer through."""

        async def open(self, address, on_notify, on_lost):
            writes = self.writes

            class HoldingLink(Link):
                async def write(self, data):
                    writes.append(bytes(data))
                    frame = zy.parse_frame(bytes(data))
                    if frame.command == zy.Command.MAX_MODE and frame.payload == bytes.fromhex("03800000"):
                        held.append(lambda s=frame.sequence: on_notify(_answer(zy.Command.MAX_MODE, bytes.fromhex("03800001"), s)))

            return HoldingLink(writes)

    wire = SlowG200()
    app = create_app(demo=True, data_dir=tmp_path)
    app.state.hub.store.update_settings({"sync_interval": 0.05})
    app.state.hub.registry.drivers["zhiyun"] = ZhiyunDriver(DriverContext(), transport=wire, sleep=_nosleep, reply_timeout=0)
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        _until(ws, lambda m: m["type"] == "hello")
        light = _molus(client, ws, wire)
        held.clear()  # the handshake's own Max Mode query; nobody waits for its answer
        _wait(lambda: held, "Gaffer to ask the light about Max Mode")
        ws.send_json({"type": "set", "light": light, "patch": {"brightness": 40}})
        _wait(lambda: _light(client, "Zhiyun panel")["state"]["brightness"] == 40, "the slider at 40%")
        client.portal.call(lambda: [answer() for answer in list(held)])  # the light answers late: Max on
        _wait(lambda: _light(client, "Zhiyun panel")["max_mode"] is True, "Max Mode to show as on")
        assert _light(client, "Zhiyun panel")["state"]["brightness"] == 40


def test_max_on_in_gaffer_shows_full_power_and_max_off_goes_back_to_the_earlier_level(studio):
    """Captain, 18 Oct: at 33% he switched Max on in Gaffer. The G200 went to 100% by itself and stayed
    there after Max off, while Gaffer showed 33% throughout. He chose: Max off goes back to 33%."""
    client, wire = studio
    with client.websocket_connect("/ws") as ws:
        _until(ws, lambda m: m["type"] == "hello")
        light = _molus(client, ws, wire)
        ws.send_json({"type": "set", "light": light, "patch": {"brightness": 33}})
        _wait(lambda: _light(client, "Zhiyun panel")["state"]["brightness"] == 33, "Gaffer at 33%")

        assert _ask(ws, {"type": "light.max_mode", "light": light, "on": True}, 1)["type"] == "ack"
        assert _light(client, "Zhiyun panel")["state"]["brightness"] == 100

        before = len(wire.writes)
        assert _ask(ws, {"type": "light.max_mode", "light": light, "on": False}, 2)["type"] == "ack"
        assert _light(client, "Zhiyun panel")["state"]["brightness"] == 33
        _wait(lambda: any(zy.parse_frame(w).command == zy.Command.SET_BRIGHTNESS for w in wire.writes[before:]),
              "the light to be told 33% again")
        sent = [zy.parse_frame(w) for w in wire.writes[before:] if zy.parse_frame(w).command == zy.Command.SET_BRIGHTNESS]
        assert round(zy.decode_brightness_response(sent[-1].payload)) == 33


def test_max_off_when_max_is_already_off_keeps_the_current_level(studio):
    """Review round 1: a saved level must not come back once Max Mode has already ended (here, by power-off)."""
    client, wire = studio
    with client.websocket_connect("/ws") as ws:
        _until(ws, lambda m: m["type"] == "hello")
        light = _molus(client, ws, wire)
        ws.send_json({"type": "set", "light": light, "patch": {"brightness": 33}})
        _wait(lambda: _light(client, "Zhiyun panel")["state"]["brightness"] == 33, "Gaffer at 33%")
        assert _ask(ws, {"type": "light.max_mode", "light": light, "on": True}, 1)["type"] == "ack"
        ws.send_json({"type": "power", "light": light, "on": False})  # ends Max Mode on the light
        _wait(lambda: _light(client, "Zhiyun panel")["max_mode"] is False, "Max Mode to end at power-off")
        ws.send_json({"type": "power", "light": light, "on": True})
        ws.send_json({"type": "set", "light": light, "patch": {"brightness": 70}})
        _wait(lambda: _light(client, "Zhiyun panel")["state"]["brightness"] == 70, "Gaffer at 70%")
        assert _ask(ws, {"type": "light.max_mode", "light": light, "on": False}, 2)["type"] == "ack"
        assert _light(client, "Zhiyun panel")["state"]["brightness"] == 70


def test_a_slider_move_during_a_slow_max_on_write_is_kept(tmp_path, monkeypatch):
    """Review round 1: Max on must not put 100% over a level set while its write was on the way."""
    import asyncio

    monkeypatch.setattr(demo, "PACE", 0.05)

    class SlowWire(Wire):
        async def open(self, address, on_notify, on_lost):
            writes = self.writes

            class SlowLink(Link):
                async def write(self, data):
                    frame = zy.parse_frame(bytes(data))
                    if frame.command == zy.Command.MAX_MODE and frame.payload != zy.encode_query():
                        await asyncio.sleep(1.0)  # a light slow to take the write
                    writes.append(bytes(data))

            return SlowLink(writes)

    wire = SlowWire()
    app = create_app(demo=True, data_dir=tmp_path)
    app.state.hub.registry.drivers["zhiyun"] = ZhiyunDriver(DriverContext(), transport=wire, sleep=_nosleep, reply_timeout=0)
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        _until(ws, lambda m: m["type"] == "hello")
        light = _molus(client, ws, wire)
        ws.send_json({"type": "set", "light": light, "patch": {"brightness": 33}})
        _wait(lambda: _light(client, "Zhiyun panel")["state"]["brightness"] == 33, "Gaffer at 33%")
        ws.send_json({"type": "light.max_mode", "light": light, "on": True, "rid": 1})
        ws.send_json({"type": "set", "light": light, "patch": {"brightness": 50}})  # while the write is on its way
        assert _until(ws, lambda m: m.get("rid") == 1)["type"] == "ack"
        assert _light(client, "Zhiyun panel")["state"]["brightness"] == 50
        ws.send_json({"type": "set", "light": light, "patch": {"brightness": 100}})
        _wait(lambda: _light(client, "Zhiyun panel")["state"]["brightness"] == 100, "Gaffer at 100%")
        assert _ask(ws, {"type": "light.max_mode", "light": light, "on": False}, 2)["type"] == "ack"
        assert _light(client, "Zhiyun panel")["state"]["brightness"] == 50  # back to the newest level, not 33


def test_max_on_from_gaffer_keeps_gaffers_colour_temperature_over_the_lights_4300k(studio):
    """Captain, 18 Oct: at 51% and 5700 K he switches Max on in Gaffer. The G200 jumps to 100% and 4300 K by
    itself; Gaffer must send 5700 K straight back and keep showing it, and Max off goes back to 51%."""
    client, wire = studio
    with client.websocket_connect("/ws") as ws:
        _until(ws, lambda m: m["type"] == "hello")
        light = _molus(client, ws, wire)
        ws.send_json({"type": "set", "light": light, "patch": {"brightness": 51, "cct": {"kelvin": 5700}}})
        _wait(lambda: _light(client, "Zhiyun panel")["state"]["cct"]["kelvin"] == 5700, "Gaffer at 5700 K")

        before = len(wire.writes)
        assert _ask(ws, {"type": "light.max_mode", "light": light, "on": True}, 1)["type"] == "ack"
        state = _light(client, "Zhiyun panel")["state"]
        assert (state["brightness"], state["cct"]["kelvin"]) == (100, 5700)

        def frames(command):
            return [zy.parse_frame(w) for w in wire.writes[before:] if zy.parse_frame(w).command == command]

        _wait(lambda: frames(zy.Command.SET_COLOR_TEMP), "5700 K to be sent after Max Mode came on")
        assert int.from_bytes(frames(zy.Command.SET_COLOR_TEMP)[-1].payload[3:5], "little") == 5700
        max_at = next(i for i, w in enumerate(wire.writes[before:]) if zy.parse_frame(w).command == zy.Command.MAX_MODE)
        cct_at = max(i for i, w in enumerate(wire.writes[before:]) if zy.parse_frame(w).command == zy.Command.SET_COLOR_TEMP)
        assert cct_at > max_at  # after the light's own 4300 K, not before it

        ws.send_json({"type": "set", "light": light, "patch": {"cct": {"kelvin": 6500}}})  # changed while in Max
        _wait(lambda: _light(client, "Zhiyun panel")["state"]["cct"]["kelvin"] == 6500, "Gaffer at 6500 K")
        assert _ask(ws, {"type": "light.max_mode", "light": light, "on": False}, 2)["type"] == "ack"
        state = _light(client, "Zhiyun panel")["state"]
        assert (state["brightness"], state["cct"]["kelvin"]) == (51, 6500)  # back to 51%; the new kelvin stays


def test_max_from_the_light_then_a_new_kelvin_in_gaffer_keeps_that_kelvin_at_max_off(tmp_path, monkeypatch):
    """Review round 2: Max pressed on the light shows 4300 K; a colour temperature then set in Gaffer must
    survive Max off in Gaffer, as it does when Max came on from Gaffer."""
    from gaffer import hub as hub_module

    monkeypatch.setattr(demo, "PACE", 0.05)
    monkeypatch.setattr(hub_module, "SETTLE_SECONDS", 0.0)
    unit = {"max": False}

    class G200(Wire):
        async def open(self, address, on_notify, on_lost):
            writes = self.writes

            class AnsweringLink(Link):
                async def write(self, data):
                    writes.append(bytes(data))
                    frame = zy.parse_frame(bytes(data))
                    if frame.command == zy.Command.MAX_MODE and frame.payload == bytes.fromhex("03800000"):
                        on_notify(_answer(zy.Command.MAX_MODE, bytes.fromhex("038000") + bytes([unit["max"]]), frame.sequence))
                    elif frame.command == zy.Command.MAX_MODE:
                        unit["max"] = frame.payload[-1] == 1  # a Max Mode write from Gaffer

            return AnsweringLink(writes)

    wire = G200()
    app = create_app(demo=True, data_dir=tmp_path)
    app.state.hub.store.update_settings({"sync_interval": 0.05})
    app.state.hub.registry.drivers["zhiyun"] = ZhiyunDriver(DriverContext(), transport=wire, sleep=_nosleep, reply_timeout=0)
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        _until(ws, lambda m: m["type"] == "hello")
        light = _molus(client, ws, wire)
        ws.send_json({"type": "set", "light": light, "patch": {"brightness": 51, "cct": {"kelvin": 5700}}})
        _wait(lambda: _light(client, "Zhiyun panel")["state"]["cct"]["kelvin"] == 5700, "Gaffer at 5700 K")
        unit["max"] = True  # Max pressed on the light
        _wait(lambda: _light(client, "Zhiyun panel")["state"]["cct"]["kelvin"] == 4300, "the light's 4300 K")
        ws.send_json({"type": "set", "light": light, "patch": {"cct": {"kelvin": 6500}}})
        _wait(lambda: _light(client, "Zhiyun panel")["state"]["cct"]["kelvin"] == 6500, "Gaffer at 6500 K")
        assert _ask(ws, {"type": "light.max_mode", "light": light, "on": False}, 1)["type"] == "ack"
        state = _light(client, "Zhiyun panel")["state"]
        assert (state["brightness"], state["cct"]["kelvin"]) == (51, 6500)


def test_a_fast_mix_of_controls_sends_the_g200_one_command_at_a_time(tmp_path, monkeypatch):
    """Captain, 18 Oct: after fast brightness, colour temperature and Max Mode changes the G200 stopped
    taking Bluetooth commands until he power-cycled it. Gaffer had written to it back to back. Now each
    write waits for the light's answer before the next goes out, and the latest setting still arrives."""
    import asyncio
    import random

    monkeypatch.setattr(demo, "PACE", 0.05)
    in_flight = {"now": 0, "most": 0}

    class AnsweringG200(Wire):
        """Answers every frame 20 ms after it arrives, echoing its sequence, as the real light does."""

        async def open(self, address, on_notify, on_lost):
            writes = self.writes
            loop = asyncio.get_running_loop()

            def answer(frame):
                in_flight["now"] -= 1
                on_notify(_answer(frame.command, frame.payload, frame.sequence))

            class Link_(Link):
                async def write(self, data):
                    writes.append(bytes(data))
                    in_flight["now"] += 1
                    in_flight["most"] = max(in_flight["most"], in_flight["now"])
                    loop.call_later(0.02, answer, zy.parse_frame(bytes(data)))

            return Link_(writes)

    wire = AnsweringG200()
    app = create_app(demo=True, data_dir=tmp_path)
    app.state.hub.registry.drivers["zhiyun"] = ZhiyunDriver(DriverContext(), transport=wire, sleep=_nosleep)
    rng = random.Random(18)
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        _until(ws, lambda m: m["type"] == "hello")
        light = _molus(client, ws, wire)
        for i in range(60):
            choice = i % 3
            if choice == 0:
                ws.send_json({"type": "set", "light": light, "patch": {"brightness": rng.randint(5, 100)}})
            elif choice == 1:
                ws.send_json({"type": "set", "light": light, "patch": {"cct": {"kelvin": rng.randrange(2700, 6500, 100)}}})
            else:
                ws.send_json({"type": "light.max_mode", "light": light, "on": i % 2 == 0, "rid": i})
        ws.send_json({"type": "set", "light": light, "patch": {"brightness": 42, "cct": {"kelvin": 3300}}, "fade": 0})
        _wait(lambda: any(zy.parse_frame(w).command == zy.Command.SET_COLOR_TEMP
                          and int.from_bytes(zy.parse_frame(w).payload[3:5], "little") == 3300 for w in wire.writes),
              "the last colour temperature to reach the light", seconds=15)
        assert in_flight["most"] == 1, f"{in_flight['most']} commands were sent before the light answered"
