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
    """Set Key light to ``level``, then a third light to a different level as a marker.

    Return what Fill reported before the marker. The marker level differs from ``level`` and from
    where the third light already sits, so it always reports.
    """
    marker = level + 1
    ws.send_json({"type": "set", "light": key, "patch": {"brightness": level}})
    ws.send_json({"type": "set", "light": barrier, "patch": {"brightness": marker}})
    seen = []
    while True:
        m = _until(ws, lambda m: m["type"] == "state" and m["light"] in (fill, barrier) and m["state"]["brightness"] in (level, marker))
        if m["light"] == barrier:
            return seen
        seen.append(m["state"]["brightness"])


def _lights(ws):
    hello = _until(ws, lambda m: m["type"] == "hello")
    ids = {light["name"]: light["id"] for light in hello["lights"]}
    return ids["Key light"], ids["Fill"], ids["Hair light"]


def test_a_group_moves_together_until_it_is_deleted(client):
    with client.websocket_connect("/ws") as ws:
        key, fill, barrier = _lights(ws)

        ws.send_json({"type": "group.save", "group": {"name": "Pair", "members": [key, fill], "props": ["brightness"]}})
        group = _until(ws, lambda m: m["type"] == "ack")["group"]
        assert 37 in _fill_levels_after(ws, key, fill, barrier, 37)  # the other light followed

        ws.send_json({"type": "group.delete", "id": group["id"]})
        assert _until(ws, lambda m: m["type"] == "groups")["groups"] == []
        assert 71 not in _fill_levels_after(ws, key, fill, barrier, 71)  # and no longer does
        # Fill still reports its own changes, so "no 71" above is a real absence, not a silent socket.
        ws.send_json({"type": "set", "light": fill, "patch": {"brightness": 55}})
        _until(ws, lambda m: m["type"] == "state" and m["light"] == fill and m["state"]["brightness"] == 55)


def test_a_group_that_shares_nothing_moves_nothing(client):
    """Turning off the last shared property must not flip the group to 'share everything'."""
    with client.websocket_connect("/ws") as ws:
        key, fill, barrier = _lights(ws)

        ws.send_json({"type": "group.save", "group": {"name": "Pair", "members": [key, fill], "props": ["brightness"]}})
        group = _until(ws, lambda m: m["type"] == "ack")["group"]

        ws.send_json({"type": "group.save", "group": {**group, "props": []}})
        saved = _until(ws, lambda m: m["type"] == "ack")["group"]
        assert saved["props"] == []
        assert 37 not in _fill_levels_after(ws, key, fill, barrier, 37)
