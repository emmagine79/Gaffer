"""The WebSocket protocol end to end, against the simulated mesh of demo lights."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from gaffer import demo
from gaffer.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "PACE", 0.05)
    app = create_app(demo=True, data_dir=tmp_path)
    with TestClient(app) as c:
        yield c


def _until(ws, predicate, limit=400):
    for _ in range(limit):
        message = ws.receive_json()
        if predicate(message):
            return message
    raise AssertionError("expected message never arrived")


def _hello(ws):
    hello = ws.receive_json()
    assert hello["type"] == "hello"
    return hello


def _ids(hello):
    return {light["name"]: light["id"] for light in hello["lights"]}


def _state_of(light_id, predicate=lambda s: True):
    return lambda m: m["type"] == "state" and m["light"] == light_id and predicate(m["state"])


# -- the basics, on the light being edited ----------------------------------------------


def test_hello_carries_every_light_and_everything_the_ui_needs(client):
    with client.websocket_connect("/ws") as ws:
        hello = _hello(ws)
        names = {light["name"]: light for light in hello["lights"]}
        assert set(names) == {"Key light", "Fill", "Backlight", "Hair light", "Zhiyun panel", "Yongnuo wand"}
        assert names["Key light"]["caps"]["name"] == "ML100R"
        assert names["Fill"]["caps"]["kind"] == "bicolour"
        assert names["Backlight"]["caps"]["features"]["daylight"] is True
        assert hello["selected"] == names["Key light"]["id"]
        assert len(hello["gel_tables"][names["Key light"]["gel_key"]]) == 318
        assert names["Backlight"]["gel_key"] is None
        assert len(hello["effects"]) >= 25 and "colour" in hello["effects"][0]
        assert len(hello["models"]) == 186
        assert hello["demo"] is True


def test_set_updates_state_for_every_watcher(client):
    with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
        key = _hello(a)["selected"]
        _hello(b)
        a.send_json({"type": "set", "patch": {"brightness": 33, "cct": {"kelvin": 2700}}})
        seen = _until(b, _state_of(key, lambda s: s["brightness"] == 33))
        assert seen["state"]["cct"]["kelvin"] == 2700


def test_invalid_command_returns_a_readable_error(client):
    with client.websocket_connect("/ws") as ws:
        _hello(ws)
        ws.send_json({"type": "set", "patch": {"cct": {"kelvin": 99999}}, "rid": 7})
        err = _until(ws, lambda m: m["type"] == "error")
        assert "1800-10000" in err["text"] and err["rid"] == 7
        ws.send_text("not json")
        assert _until(ws, lambda m: m["type"] == "error")


def test_effect_runs_and_streams_state(client):
    with client.websocket_connect("/ws") as ws:
        key = _hello(ws)["selected"]
        ws.send_json({"type": "engine.start", "effect": "rainbow", "params": {"period": 2}})
        _until(ws, lambda m: m["type"] == "engine" and m["light"] == key and m["engine"]["kind"] == "effect")
        hues = {_until(ws, _state_of(key))["state"]["hsi"]["hue"] for _ in range(6)}
        assert len(hues) > 1
        ws.send_json({"type": "engine.stop"})
        _until(ws, lambda m: m["type"] == "engine" and m["engine"]["kind"] is None)


def test_scenes_round_trip(client):
    with client.websocket_connect("/ws") as ws:
        key = _hello(ws)["selected"]
        ws.send_json({"type": "set", "patch": {"brightness": 71}})
        time.sleep(0.1)
        ws.send_json({"type": "store.upsert", "collection": "scenes", "item": {"name": "Reading"}})
        ack = _until(ws, lambda m: m["type"] == "ack")
        assert ack["item"]["state"]["brightness"] == 71
        ws.send_json({"type": "set", "patch": {"brightness": 5}})
        ws.send_json({"type": "scene.apply", "id": ack["item"]["id"], "fade": 0})
        _until(ws, _state_of(key, lambda s: s["brightness"] == 71))


# -- streams -----------------------------------------------------------------------------


def test_stream_socket_drives_the_light_without_broadcasts(client):
    with client.websocket_connect("/ws") as watcher, client.websocket_connect("/ws?role=stream") as stream:
        key = _hello(watcher)["selected"]
        stream.send_text("garbage is ignored")
        stream.send_json({"type": "set", "patch": {"brightness": 1}})  # not allowed on this socket
        stream.send_json({"type": "stream.begin", "source": "audio"})
        stream.send_json({"type": "stream", "frame": {"mode": "hsi", "hue": 270, "sat": 90, "brightness": 64}, "source": "audio"})
        seen = _until(watcher, _state_of(key, lambda s: s["mode"] == "hsi"))
        assert seen["state"]["hsi"]["hue"] == 270 and seen["state"]["brightness"] == 64


def _frame(hue, brightness=50, source="audio", light=None):
    message = {"type": "stream", "source": source, "frame": {"mode": "hsi", "hue": hue, "sat": 100, "brightness": brightness}}
    return {**message, "light": light} if light else message


def test_frames_without_an_open_session_are_dropped(client):
    with client.websocket_connect("/ws") as ws, client.websocket_connect("/ws?role=stream") as stream:
        key = _hello(ws)["selected"]
        stream.send_json(_frame(123))
        ws.send_json({"type": "set", "patch": {"brightness": 41}, "rid": 1})
        seen = _until(ws, _state_of(key, lambda s: s["brightness"] == 41))
        assert seen["state"]["hsi"]["hue"] != 123


def test_a_takeover_closes_the_session_so_late_frames_cannot_snatch_the_light(client):
    with client.websocket_connect("/ws") as ws, client.websocket_connect("/ws?role=stream") as stream:
        key = _hello(ws)["selected"]
        stream.send_json({"type": "stream.begin", "source": "audio"})
        stream.send_json(_frame(200))
        _until(ws, _state_of(key, lambda s: s["hsi"]["hue"] == 200))
        ws.send_json({"type": "engine.start", "effect": "rainbow", "params": {"period": 60}})
        _until(ws, lambda m: m["type"] == "engine" and m["engine"]["kind"] == "effect")
        stream.send_json(_frame(77))  # a frame still in flight from the music
        stream.send_json({"type": "stream.end", "source": "audio"})
        for _ in range(8):
            m = _until(ws, lambda m: m["type"] in ("state", "engine") and m.get("light") == key)
            if m["type"] == "engine":
                assert m["engine"]["kind"] == "effect"
            else:
                assert m["state"]["hsi"]["hue"] != 77


def test_a_stream_can_drive_a_white_only_light_as_warmth(client):
    with client.websocket_connect("/ws") as ws, client.websocket_connect("/ws?role=stream") as stream:
        fill = _ids(_hello(ws))["Fill"]
        stream.send_json({"type": "stream.begin", "source": "screen", "light": fill})
        stream.send_json(_frame(0, 60, "screen", fill))  # pure red
        seen = _until(ws, _state_of(fill, lambda s: s["brightness"] == 60))
        assert seen["state"]["mode"] == "cct" and seen["state"]["cct"]["kelvin"] == 2800


# -- several lights -------------------------------------------------------------------------


def test_each_light_is_addressed_on_its_own(client):
    with client.websocket_connect("/ws") as ws:
        ids = _ids(_hello(ws))
        ws.send_json({"type": "set", "light": ids["Fill"], "patch": {"brightness": 12}})
        seen = _until(ws, _state_of(ids["Fill"], lambda s: s["brightness"] == 12))
        assert seen["light"] == ids["Fill"]


def test_selecting_a_light_makes_it_the_default_target(client):
    with client.websocket_connect("/ws") as ws:
        ids = _ids(_hello(ws))
        ws.send_json({"type": "select", "light": ids["Fill"], "rid": 3})
        assert _until(ws, lambda m: m["type"] == "selected")["light"] == ids["Fill"]
        ws.send_json({"type": "set", "patch": {"brightness": 19}})
        _until(ws, _state_of(ids["Fill"], lambda s: s["brightness"] == 19))


def test_a_light_rejects_what_its_model_cannot_do(client):
    with client.websocket_connect("/ws") as ws:
        ids = _ids(_hello(ws))
        ws.send_json({"type": "set", "light": ids["Fill"], "patch": {"mode": "hsi"}})
        assert "no colour mode" in _until(ws, lambda m: m["type"] == "error")["text"]


def test_a_scene_from_a_colour_light_fits_a_bicolour_one(client):
    with client.websocket_connect("/ws") as ws:
        ids = _ids(_hello(ws))
        ws.send_json({"type": "set", "patch": {"mode": "hsi", "hsi": {"hue": 220, "sat": 100}, "brightness": 64}})
        time.sleep(0.1)
        ws.send_json({"type": "store.upsert", "collection": "scenes", "item": {"name": "Blue"}})
        scene = _until(ws, lambda m: m["type"] == "ack")["item"]
        ws.send_json({"type": "scene.apply", "light": ids["Fill"], "id": scene["id"], "fade": 0})
        seen = _until(ws, _state_of(ids["Fill"], lambda s: s["brightness"] == 64))
        assert seen["state"]["mode"] == "cct" and seen["state"]["cct"]["kelvin"] == 6500


def test_all_off_turns_every_light_off(client):
    with client.websocket_connect("/ws") as ws:
        ids = _ids(_hello(ws))
        ws.send_json({"type": "power.all", "on": False})
        off = set()
        while off != set(ids.values()):
            m = _until(ws, lambda m: m["type"] == "state" and not m["state"]["power"])
            off.add(m["light"])


def test_a_sync_group_mirrors_only_its_chosen_properties(client):
    with client.websocket_connect("/ws") as ws:
        ids = _ids(_hello(ws))
        group = {"name": "Key + Fill", "members": [ids["Key light"], ids["Fill"]], "props": ["brightness"]}
        ws.send_json({"type": "group.save", "group": group})
        saved = _until(ws, lambda m: m["type"] == "ack")["group"]
        assert saved["props"] == ["brightness"] and saved["enabled"]
        ws.send_json({"type": "set", "light": ids["Fill"], "patch": {"cct": {"kelvin": 3000}}})
        _until(ws, _state_of(ids["Fill"], lambda s: s["cct"]["kelvin"] == 3000))
        ws.send_json({"type": "set", "light": ids["Key light"], "patch": {"brightness": 23, "cct": {"kelvin": 6000}}})
        fill = _until(ws, _state_of(ids["Fill"], lambda s: s["brightness"] == 23))
        assert fill["state"]["cct"]["kelvin"] == 3000  # temperature was not synced


def test_a_light_follows_only_one_group(client):
    with client.websocket_connect("/ws") as ws:
        ids = _ids(_hello(ws))
        ws.send_json({"type": "group.save", "group": {"name": "A", "members": [ids["Key light"], ids["Fill"]]}})
        _until(ws, lambda m: m["type"] == "ack")
        ws.send_json({"type": "group.save", "group": {"name": "B", "members": [ids["Fill"], ids["Backlight"]]}})
        groups = _until(ws, lambda m: m["type"] == "groups" and len(m["groups"]) == 2)["groups"]
        by_name = {g["name"]: g for g in groups}
        assert by_name["A"]["members"] == [ids["Key light"]]
        assert by_name["B"]["members"] == [ids["Fill"], ids["Backlight"]]


def test_matching_copies_a_look_once_without_linking(client):
    with client.websocket_connect("/ws") as ws:
        ids = _ids(_hello(ws))
        ws.send_json({"type": "set", "patch": {"brightness": 81}})
        _until(ws, _state_of(ids["Key light"], lambda s: s["brightness"] == 81))
        ws.send_json({"type": "group.match", "targets": [ids["Backlight"]], "props": ["brightness"]})
        _until(ws, _state_of(ids["Backlight"], lambda s: s["brightness"] == 81))


def test_scanning_and_pairing_a_new_light(client):
    with client.websocket_connect("/ws") as ws:
        before = _hello(ws)
        ws.send_json({"type": "lights.scan", "seconds": 2, "rid": 1})
        found = _until(ws, lambda m: m["type"] == "ack" and m["of"] == "lights.scan")["nearby"]
        fresh = next(n for n in found if n["relation"] == "unpaired")
        assert fresh["model"] == "TL60"
        assert any(n["relation"] == "elsewhere" for n in found)
        ws.send_json({"type": "lights.pair", "address": fresh["address"], "name": "Tube"})
        steps = []
        while "done" not in steps:
            steps.append(_until(ws, lambda m: m["type"] == "pairing")["pairing"]["step"])
        assert steps[:3] == ["starting", "provisioning", "binding"]
        lights = _until(ws, lambda m: m["type"] == "lights")["lights"]
        tube = next(light for light in lights if light["name"] == "Tube")
        assert tube["caps"]["name"] == "TL60" and tube["node_address"] == 14
        assert len(lights) == len(before["lights"]) + 1


def test_rename_model_place_and_forget(client):
    with client.websocket_connect("/ws") as ws:
        ids = _ids(_hello(ws))
        fill = ids["Fill"]
        ws.send_json({"type": "lights.rename", "light": fill, "name": "Soft fill"})
        lights = _until(ws, lambda m: m["type"] == "lights")["lights"]
        assert any(light["name"] == "Soft fill" for light in lights)
        ws.send_json({"type": "lights.model", "light": fill, "radio_id": "00D0"})  # SL300Bi, with tint
        lights = _until(ws, lambda m: m["type"] == "lights")["lights"]
        changed = next(light for light in lights if light["id"] == fill)
        assert changed["caps"]["name"] == "SL300Bi" and changed["model_source"] == "manual"
        ws.send_json({"type": "lights.model", "light": fill, "radio_id": "nope"})
        assert "pick a model" in _until(ws, lambda m: m["type"] == "error")["text"]
        ws.send_json({"type": "lights.place", "light": fill, "x": 1.7, "y": 0.25})
        placed = _until(ws, lambda m: m["type"] == "placed")
        assert (placed["x"], placed["y"]) == (1.0, 0.25)
        ws.send_json({"type": "lights.forget", "light": fill})
        lights = _until(ws, lambda m: m["type"] == "lights")["lights"]
        assert fill not in {light["id"] for light in lights}


def test_device_settings_are_offered_only_where_the_model_has_them(client):
    with client.websocket_connect("/ws") as ws:
        ids = _ids(_hello(ws))
        ws.send_json({"type": "fan", "light": ids["Fill"], "mode": 1})
        assert "no fan mode" in _until(ws, lambda m: m["type"] == "error")["text"]
        _until(ws, lambda m: m["type"] == "link" and m["link"]["status"] == "connected")
        ws.send_json({"type": "fan", "light": ids["Key light"], "mode": 1})
        device = _until(ws, lambda m: m["type"] == "device")
        assert device["light"] == ids["Key light"] and device["device"]["fan"] == 1
