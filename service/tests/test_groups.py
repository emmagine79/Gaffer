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


class Studio:
    """The demo lights over one socket. Key light and Fill are the group; Backlight is on screen but not in it."""

    def __init__(self, ws):
        hello = _until(ws, lambda m: m["type"] == "hello")
        by_name = {light["name"]: light for light in hello["lights"]}
        self.ws = ws
        self.key, self.fill = by_name["Key light"]["id"], by_name["Fill"]["id"]
        self.outsider, self.marker_light = by_name["Backlight"]["id"], by_name["Hair light"]["id"]
        self.start = {light["id"]: light["state"] for light in hello["lights"]}
        self._marker = 0

    def save_group(self, group, leader=None):
        self.ws.send_json({"type": "group.save", "group": group, "leader": leader})
        return _until(self.ws, lambda m: m["type"] == "ack")["group"]

    def settle(self, *commands):
        """Send the commands, then a marker on Hair light; return the states each light reported before the marker.

        The marker light is last in the broadcast order and always changes, so everything the commands moved
        has been reported when it arrives.
        """
        for light, patch in commands:
            self.ws.send_json({"type": "set", "light": light, "patch": patch})
        self._marker += 1
        level = 90 + self._marker
        self.ws.send_json({"type": "set", "light": self.marker_light, "patch": {"brightness": level}})
        seen: dict[str, list[dict]] = {}
        while True:
            m = _until(self.ws, lambda m: m["type"] == "state")
            if m["light"] == self.marker_light and m["state"]["brightness"] == level:
                return seen
            seen.setdefault(m["light"], []).append(m["state"])


def _levels(seen, light):
    return [s["brightness"] for s in seen.get(light, [])]


def test_a_group_moves_together_until_it_is_deleted(client):
    with client.websocket_connect("/ws") as ws:
        studio = Studio(ws)
        assert studio.start[studio.fill]["brightness"] not in (37, 71)  # so "followed" and "did not" differ

        group = studio.save_group({"name": "Pair", "members": [studio.key, studio.fill], "props": ["brightness"]}, studio.key)
        assert 37 in _levels(studio.settle((studio.key, {"brightness": 37})), studio.fill)  # the other light followed

        ws.send_json({"type": "group.delete", "id": group["id"]})
        assert _until(ws, lambda m: m["type"] == "groups")["groups"] == []
        seen = studio.settle((studio.key, {"brightness": 71}))
        assert _levels(seen, studio.key) == [71]  # Key light moved in this very run
        assert 71 not in _levels(seen, studio.fill)  # and Fill, which followed at 37 above, no longer does


def test_a_group_that_shares_nothing_moves_nothing(client):
    """Turning off the last shared property must not flip the group to 'share everything'."""
    with client.websocket_connect("/ws") as ws:
        studio = Studio(ws)
        group = studio.save_group({"name": "Pair", "members": [studio.key, studio.fill], "props": ["brightness"]}, studio.key)
        assert 37 in _levels(studio.settle((studio.key, {"brightness": 37})), studio.fill)  # it follows first

        saved = studio.save_group({**group, "props": []}, studio.key)
        assert saved["props"] == []
        seen = studio.settle((studio.key, {"brightness": 71}))
        assert _levels(seen, studio.key) == [71]
        assert 71 not in _levels(seen, studio.fill)


def test_switching_a_group_back_on_from_a_light_outside_it_moves_nothing(client):
    with client.websocket_connect("/ws") as ws:
        studio = Studio(ws)
        group = studio.save_group({"name": "Pair", "members": [studio.key, studio.fill], "props": ["brightness"]}, studio.key)
        studio.save_group({**group, "enabled": False}, studio.key)
        studio.settle((studio.key, {"brightness": 20}), (studio.fill, {"brightness": 80}))  # now they differ

        # The user is looking at Backlight, which is not in the group.
        ws.send_json({"type": "group.save", "group": {**group, "enabled": True}, "leader": studio.outsider})
        _until(ws, lambda m: m["type"] == "ack")
        seen = studio.settle()
        assert studio.key not in seen and studio.fill not in seen  # neither light was told anything

        # The same save from a member lines the group up behind that member.
        studio.save_group({**group, "enabled": False}, studio.key)
        studio.save_group({**group, "enabled": True}, studio.key)
        assert 20 in _levels(studio.settle(), studio.fill)


def test_adding_a_shared_property_from_a_light_outside_the_group_moves_nothing(client):
    with client.websocket_connect("/ws") as ws:
        studio = Studio(ws)
        group = studio.save_group({"name": "Pair", "members": [studio.key, studio.fill], "props": ["brightness"]}, studio.key)
        studio.settle((studio.fill, {"power": False}))  # power is not shared, so Key stays on
        assert studio.start[studio.key]["power"] is True

        studio.save_group({**group, "props": ["brightness", "power"]}, studio.outsider)
        seen = studio.settle()
        assert studio.key not in seen and studio.fill not in seen  # Fill stays off

        # A member leading the same change does line the group up.
        studio.save_group({**group, "props": ["brightness"]}, studio.key)
        studio.save_group({**group, "props": ["brightness", "power"]}, studio.key)
        assert any(s["power"] for s in studio.settle().get(studio.fill, []))
