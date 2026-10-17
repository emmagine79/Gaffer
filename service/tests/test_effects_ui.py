"""SPEC-012 acceptance tests: what the effects section of Glass is built from, through the real WebSocket.

Glass lists a light's built-in effects from ``caps.effects`` and starts Gaffer's own with
``engine.start``. Demo mode, so no Bluetooth is touched.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gaffer import demo
from gaffer.app import create_app

GODOX_TABLE = Path(__file__).resolve().parents[1] / "gaffer" / "data" / "models.json"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "PACE", 0.05)
    with TestClient(create_app(demo=True, data_dir=tmp_path)) as c:
        yield c


def _until(ws, predicate, limit=600):
    for _ in range(limit):
        message = ws.receive_json()
        if predicate(message):
            return message
    raise AssertionError("expected message never arrived")


def _lights(ws):
    hello = ws.receive_json()
    assert hello["type"] == "hello"
    return {light["name"]: light for light in hello["lights"]}


def test_built_in_list_is_the_model_row_and_zhiyun_has_none(client):
    """AC1: a Godox light's built-in effects are its model row's; the Zhiyun light has none."""
    row = json.loads(GODOX_TABLE.read_text())["003A"]  # SL60IIBi, the demo's Fill light
    with client.websocket_connect("/ws") as ws:
        lights = _lights(ws)
    assert [e["name"] for e in lights["Fill"]["caps"]["effects"]] == [e["name"] for e in sorted(row["effects"], key=lambda e: e["symbol"])]
    assert lights["Zhiyun panel"]["caps"]["effects"] == [] and lights["Zhiyun panel"]["caps"]["features"]["builtin_effects"] == 0


def test_breathe_moves_a_cct_only_lights_brightness_and_colour_cycle_plays_as_warmth(client):
    """AC2: Gaffer's own effects run through the engine on a light with only white."""
    with client.websocket_connect("/ws") as ws:
        wand = _lights(ws)["Yongnuo wand"]
        assert wand["caps"]["features"]["colour"] is False and wand["caps"]["effects"] == []

        def states(effect, params):
            ws.send_json({"type": "engine.start", "light": wand["id"], "effect": effect, "params": params})
            _until(ws, lambda m: m["type"] == "engine" and m["light"] == wand["id"] and m["engine"]["effect"] == effect)
            seen = [_until(ws, lambda m: m["type"] == "state" and m["light"] == wand["id"])["state"] for _ in range(8)]
            ws.send_json({"type": "engine.stop", "light": wand["id"]})
            _until(ws, lambda m: m["type"] == "engine" and m["engine"]["kind"] is None)
            return seen

        breathing = states("breathe", {"period": 1})
        assert {s["mode"] for s in breathing} == {"cct"}
        assert len({round(s["brightness"]) for s in breathing}) > 3

        cycling = states("rainbow", {"period": 1})
        assert {s["mode"] for s in cycling} == {"cct"}
        assert len({s["cct"]["kelvin"] for s in cycling}) > 3
