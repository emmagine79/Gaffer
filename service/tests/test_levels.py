"""SPEC-007: one fader over several lights keeps their levels relative to each other."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from gaffer import demo
from gaffer.app import create_app
from gaffer.levels import scale_levels


def test_followers_keep_their_ratio_to_the_anchor_and_stop_at_100():
    assert scale_levels({"a": 40, "b": 25, "c": 60}, "a", 80) == {"a": 80, "b": 50, "c": 100}


def test_an_anchor_at_zero_moves_the_others_by_the_same_step():
    assert scale_levels({"a": 0, "b": 25, "c": 60}, "a", 10) == {"a": 10, "b": 35, "c": 70}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "PACE", 0.05)
    with TestClient(create_app(demo=True, data_dir=tmp_path)) as c:
        yield c


def _levels(client):
    return {light["name"]: light["state"]["brightness"] for light in client.get("/api/lights").json()["lights"]}


def _send(ws, message):
    ws.send_json({**message, "rid": 1})
    while True:
        reply = ws.receive_json()
        if reply.get("rid") == 1:
            return reply


def test_set_many_over_the_socket_moves_every_light_and_a_refusal_moves_none(client):
    with client.websocket_connect("/ws") as ws:
        hello = ws.receive_json()
        ids = {light["name"]: light["id"] for light in hello["lights"]}
        trio = [ids["Key light"], ids["Fill"], ids["Hair light"]]
        for light_id, level in zip(trio, (40, 25, 60)):
            ws.send_json({"type": "set", "light": light_id, "patch": {"brightness": level}})
        assert _send(ws, {"type": "set.many", "anchor": trio[0], "lights": trio, "brightness": 80})["type"] == "ack"
        after = _levels(client)
        assert [after[n] for n in ("Key light", "Fill", "Hair light")] == [80, 50, 100]

        reply = _send(ws, {"type": "set.many", "anchor": trio[0], "lights": [*trio, "no-such-light"], "brightness": 10})
        assert reply["type"] == "error" and "/Users/" not in reply["text"]
        assert _levels(client) == after

        # More ids than the studio has lights, and a level that is not a number: refused, nothing moves.
        crowd = [trio[0]] * (len(hello["lights"]) + 1)
        for bad in ({"lights": crowd, "brightness": 10}, {"lights": trio, "brightness": "10"}, {"lights": trio, "brightness": None}):
            assert _send(ws, {"type": "set.many", "anchor": trio[0], **bad})["type"] == "error"
        assert _levels(client) == after


def test_a_drag_to_zero_and_back_gives_the_original_balance(client):
    with client.websocket_connect("/ws") as ws:
        hello = ws.receive_json()
        ids = {light["name"]: light["id"] for light in hello["lights"]}
        trio = [ids["Key light"], ids["Fill"], ids["Hair light"]]
        start = dict(zip(trio, (40, 25, 60)))
        for light_id, level in start.items():
            ws.send_json({"type": "set", "light": light_id, "patch": {"brightness": level}})
        drag = {"type": "set.many", "anchor": trio[0], "lights": trio, "start_levels": start}

        assert _send(ws, {**drag, "brightness": 0})["type"] == "ack"
        assert [_levels(client)[n] for n in ("Key light", "Fill", "Hair light")] == [0, 0, 0]
        assert _send(ws, {**drag, "brightness": 40})["type"] == "ack"
        assert [_levels(client)[n] for n in ("Key light", "Fill", "Hair light")] == [40, 25, 60]

        # start_levels that do not cover exactly these lights, or hold a bad level, are refused and nothing moves.
        for bad in ({trio[0]: 40}, {**start, trio[1]: 101}, {**start, trio[1]: "25"}, "40"):
            assert _send(ws, {**drag, "start_levels": bad, "brightness": 10})["type"] == "error"
        assert [_levels(client)[n] for n in ("Key light", "Fill", "Hair light")] == [40, 25, 60]


def test_an_empty_light_id_is_refused_instead_of_moving_the_selected_light(client):
    with client.websocket_connect("/ws") as ws:
        hello = ws.receive_json()
        before = _levels(client)
        for message in (
            {"anchor": "", "lights": [""], "brightness": 100},
            {"anchor": hello["lights"][0]["id"], "lights": [hello["lights"][0]["id"], ""], "brightness": 100},
        ):
            assert _send(ws, {"type": "set.many", **message})["type"] == "error"
        assert _levels(client) == before


def test_a_ratio_drag_over_grouped_lights_keeps_the_ratio_and_moves_unpicked_members_once(client):
    """SPEC-023: Key and Fill (picked) and Backlight (not picked) share brightness in one group."""
    with client.websocket_connect("/ws") as ws:
        ids = {light["name"]: light["id"] for light in ws.receive_json()["lights"]}
        key, fill, backlight = ids["Key light"], ids["Fill"], ids["Backlight"]
        for light_id, level in ((key, 40), (fill, 25), (backlight, 10)):
            ws.send_json({"type": "set", "light": light_id, "patch": {"brightness": level}})
        # The leader is a light outside the group, so joining lines nobody up and the levels stay as set.
        ws.send_json({"type": "group.save", "rid": 2, "leader": ids["Hair light"], "group": {
            "name": "Pair", "members": [key, fill, backlight], "props": ["brightness"]}})
        while ws.receive_json().get("rid") != 2:
            pass
        assert _send(ws, {"type": "set.many", "anchor": key, "lights": [key, fill], "brightness": 80})["type"] == "ack"
        after = _levels(client)
        assert (after["Key light"], after["Fill"], after["Backlight"]) == (80, 50, 80)
