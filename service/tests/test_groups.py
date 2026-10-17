"""SPEC-011: sync groups through the real WebSocket, against the demo lights."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from gaffer import demo
from gaffer.app import create_app


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


def _fill_levels_after(ws, key, fill, barrier, level):
    """Set Key light to ``level``, then a third light as a marker; return what Fill reported before the marker."""
    ws.send_json({"type": "set", "light": key, "patch": {"brightness": level}})
    ws.send_json({"type": "set", "light": barrier, "patch": {"brightness": level}})
    seen = []
    while True:
        m = _until(ws, lambda m: m["type"] == "state" and m["light"] in (fill, barrier) and m["state"]["brightness"] == level)
        if m["light"] == barrier:
            return seen
        seen.append(m["state"]["brightness"])


def test_a_group_moves_together_until_it_is_deleted(client):
    with client.websocket_connect("/ws") as ws:
        hello = _until(ws, lambda m: m["type"] == "hello")
        ids = {light["name"]: light["id"] for light in hello["lights"]}
        key, fill, barrier = ids["Key light"], ids["Fill"], ids["Hair light"]

        ws.send_json({"type": "group.save", "group": {"name": "Pair", "members": [key, fill], "props": ["brightness"]}})
        group = _until(ws, lambda m: m["type"] == "ack")["group"]
        assert 37 in _fill_levels_after(ws, key, fill, barrier, 37)  # the other light followed

        ws.send_json({"type": "group.delete", "id": group["id"]})
        assert _until(ws, lambda m: m["type"] == "groups")["groups"] == []
        assert 71 not in _fill_levels_after(ws, key, fill, barrier, 71)  # and no longer does
