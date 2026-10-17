"""SPEC-010 acceptance tests: looks with their own fade, through the running app.

The app is reached the way the Mac shell reaches it (behind the Host check and the session
secret, signed in by the cookie alone) in demo mode, so no Bluetooth is touched.
"""

from __future__ import annotations

import time
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from gaffer.app import create_app
from gaffer.session import COOKIE, protect

SECRET = "test-secret-for-looks"
WS = "ws://127.0.0.1/ws"


class FakeClock:
    """Stands in for each light's monotonic clock so a 2 s fade needs no 2 s wait."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def shell(tmp_path):
    """A client that sends the cookie itself, as ServiceClient.swift does (no /session link)."""
    app = create_app(demo=True, data_dir=tmp_path)
    with TestClient(protect(app, SECRET), base_url="http://127.0.0.1", cookies={COOKIE: SECRET}) as client:
        client.hub = app.state.hub  # type: ignore[attr-defined]
        yield client


def _lights(client):
    return {light["name"]: light for light in client.get("/api/lights").json()["lights"]}


def _wait(predicate, what, seconds=5.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError(f"never happened: {what}")


THREE = {"Key light": 21.0, "Fill": 34.0, "Backlight": 47.0}  # brightness each light must end on


def _save_three(client, name, fade):
    lights = _lights(client)
    patches = {lights[n]["id"]: {"power": True, "brightness": b, "cct": {"kelvin": 4000}} for n, b in THREE.items()}
    reply = client.post("/api/looks", json={"name": name, "fade_seconds": fade, "lights": patches})
    assert reply.status_code == 200, reply.text
    return reply.json()["look"]["id"]


def test_ac3_fade_2_starts_a_transition_on_all_three_and_fade_0_sets_them_at_once(shell):
    clock = FakeClock()
    for fixture in shell.hub.fixtures.values():
        fixture.engine._clock = clock
    slow = _save_three(shell, "Slow", 2)
    quick = _save_three(shell, "Quick", 0)
    lights = _lights(shell)
    ids = {n: lights[n]["id"] for n in THREE}

    # Fade 2: each of the three is mid-transition of duration 2, and the others are left alone.
    assert shell.post(f"/api/looks/{slow}/apply").status_code == 200
    now = _lights(shell)
    for name in THREE:
        assert now[name]["engine"]["kind"] == "transition" and now[name]["engine"]["duration"] == 2, name
    assert now["Hair light"]["engine"]["kind"] is None
    # ...and when the 2 s are up each ends on the look's values.
    clock.now += 3
    _wait(lambda: all(
        _lights(shell)[n]["engine"]["kind"] is None and _lights(shell)[n]["state"]["brightness"] == b
        for n, b in THREE.items()), "the fade finishing on the look's values")
    # The daylight-only Backlight keeps 5600 K: a look is fitted to each light that takes it.
    assert all(_lights(shell)[n]["state"]["cct"]["kelvin"] == 4000 for n in ("Key light", "Fill"))

    # Fade 0: set at once. Move the three away first, then apply and look straight away.
    shell.hub.fixtures[ids["Key light"]].state = shell.hub.fixtures[ids["Key light"]].state.model_copy(update={"brightness": 90.0})
    assert shell.post(f"/api/looks/{quick}/apply").status_code == 200
    now = _lights(shell)
    for name, brightness in THREE.items():
        assert now[name]["engine"]["kind"] is None, name
        assert now[name]["state"]["brightness"] == brightness, name


def test_the_current_look_name_is_in_hello_and_the_look_messages(shell):
    look = _save_three(shell, "Talking head", 0)
    with shell.websocket_connect(WS) as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello" and hello["look"] is None
        assert ws.receive_json() == {"type": "look", "id": None, "name": None}  # sent as the socket opens
        assert shell.post(f"/api/looks/{look}/apply").status_code == 200  # checked first: a refusal would leave the loop below waiting
        seen = []
        while not any(m["type"] == "look" for m in seen):
            seen.append(ws.receive_json())
        assert [m for m in seen if m["type"] == "look"] == [{"type": "look", "id": look, "name": "Talking head"}]
    with shell.websocket_connect(WS) as ws:
        assert ws.receive_json()["look"] == "Talking head"
        assert ws.receive_json() == {"type": "look", "id": look, "name": "Talking head"}
        assert shell.post("/api/all-off").status_code == 200
        while (message := ws.receive_json())["type"] != "look":
            pass
        assert message["name"] is None


def test_the_routes_the_mac_shell_calls(shell):
    """GET /api/looks, POST /api/looks/{id}/apply and POST /api/all-off, as ServiceClient.swift calls them."""
    first = _save_three(shell, "Talking head", 0)
    second = _save_three(shell, "Café / Night ☾", 0)
    listed = shell.get("/api/looks").json()["looks"]
    assert [x["id"] for x in listed] == [first, second]  # slot order: slot 1 is the first entry
    assert listed[1]["name"] == "Café / Night ☾"
    # The id goes in as one percent-encoded path segment (every character but the unreserved ones).
    reply = shell.post(f"/api/looks/{quote(second, safe='')}/apply")
    assert reply.status_code == 200
    assert reply.json()["ok"] is True and reply.json()["look"] == {"id": second, "name": "Café / Night ☾"}
    assert shell.post("/api/looks/nope/apply").json() == {
        "error": "look_not_found", "message": "There is no look with that id."}
    assert shell.post("/api/looks/nope/apply").status_code == 404
    # A refused save says why in plain words and stores nothing (checklist 1, 6, 7, 15).
    ids = [x["id"] for x in shell.get("/api/looks").json()["looks"]]
    for body in ({"name": " "}, {"name": "x" * 81}, {"name": "a\nb"}, {"name": "ok", "fade_seconds": 61}, {"name": "ok", "fade_seconds": True},
                 {"name": "ok", "id": "constructor"}, {"name": "ok", "id": "../x"}, {"name": "ok", "lights": {"nope": {}}},
                 {"name": "ok", "lights": {next(iter(_lights(shell).values()))["id"]: {"mode": "nonsense"}}}):
        refused = shell.post("/api/looks", json=body)
        assert refused.status_code == 400 and refused.json()["error"] == "look_not_valid", body
        assert not any(p in refused.text for p in ("/Users/", "/private/", "/var/", "Traceback")), refused.text
    assert [x["id"] for x in shell.get("/api/looks").json()["looks"]] == ids
    assert shell.post("/api/all-off").json() == {"ok": True}
    assert not any(light["state"]["power"] for light in _lights(shell).values())
    # Without the cookie none of it works.
    shell.cookies.clear()
    for method, path in (("get", "/api/looks"), ("post", f"/api/looks/{first}/apply"), ("post", "/api/all-off")):
        assert getattr(shell, method)(path).status_code == 401
