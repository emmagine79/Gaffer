"""SPEC-010 acceptance tests: looks with their own fade, through the running app.

The app is reached the way the Mac shell reaches it (behind the Host check and the session
secret, signed in by the cookie alone) in demo mode, so no Bluetooth is touched.
"""

from __future__ import annotations

import dataclasses
import json
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


#: A looks.json somebody edited by hand: one entry with an unreadable fade, one with no id at all.
HAND_EDITED = [{"id": "night", "name": "Night", "fade_seconds": "slow", "lights": {}}, {"name": "No id at all"}]


@pytest.fixture
def hand_edited(tmp_path):
    (tmp_path / "looks.json").write_text(json.dumps(HAND_EDITED), encoding="utf-8")
    app = create_app(demo=True, data_dir=tmp_path)
    with TestClient(protect(app, SECRET), base_url="http://127.0.0.1", cookies={COOKIE: SECRET}) as client:
        client.hub = app.state.hub  # type: ignore[attr-defined]
        client.file = tmp_path / "looks.json"  # type: ignore[attr-defined]
        yield client


def _lights(client):
    return {light["name"]: light for light in client.get("/api/lights").json()["lights"]}


def _tick_lights(client):
    """Run one engine step on every light, on the app's own event loop where the engines run,
    so a fade that the fake clock says is over is finished now and nothing races it."""
    async def step():
        for fixture in client.hub.fixtures.values():
            fixture.engine.tick()
    client.portal.call(step)


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
    _tick_lights(shell)
    finished = _lights(shell)
    assert all(finished[n]["engine"]["kind"] is None and finished[n]["state"]["brightness"] == b for n, b in THREE.items())
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
    assert shell.post("/api/all-off").json() == {"ok": True, "skipped": []}
    assert not any(light["state"]["power"] for light in _lights(shell).values())
    # Without the cookie none of it works.
    shell.cookies.clear()
    for method, path in (("get", "/api/looks"), ("post", f"/api/looks/{first}/apply"), ("post", "/api/all-off")):
        assert getattr(shell, method)(path).status_code == 401


def test_a_page_on_another_port_cannot_post_to_the_lights(shell):
    """CSRF: SameSite does not separate localhost ports, so a foreign Origin is refused and nothing changes."""
    look = _save_three(shell, "Talking head", 0)
    assert any(light["state"]["power"] for light in _lights(shell).values())
    for origin in ("http://127.0.0.1:9", "http://evil.example", "null"):
        for path in ("/api/all-off", f"/api/looks/{look}/apply", "/api/looks"):
            refused = shell.post(path, headers={"origin": origin}, json={"name": "x"})
            assert refused.status_code == 403 and refused.json()["error"] == "origin_not_allowed", (origin, path)
    assert any(light["state"]["power"] for light in _lights(shell).values())
    assert len(shell.get("/api/looks").json()["looks"]) == 1
    assert shell.hub.look is None
    # The page's own origin and the shell (no Origin) still work; a POST body must say it is JSON.
    assert shell.post("/api/all-off", headers={"origin": "http://127.0.0.1"}).status_code == 200
    assert shell.post("/api/looks", content='{"name": "x"}', headers={"content-type": "text/plain"}).status_code == 415


def test_a_look_can_be_edited_and_applied_whatever_its_name(shell):
    """Ids made from names such as Constructor, or from an 80 character name saved twice, stay editable."""
    long_name = "x" * 80
    ids = []
    for name in ("Constructor", "Prototype", long_name, long_name):
        saved = shell.post("/api/looks", json={"name": name, "fade_seconds": 1}).json()["look"]
        edited = shell.post("/api/looks", json={"id": saved["id"], "name": name, "fade_seconds": 3})
        assert edited.status_code == 200, (name, edited.text)
        assert shell.post(f"/api/looks/{saved['id']}/apply").status_code == 200, name
        ids.append(saved["id"])
    assert len(set(ids)) == 4
    assert [x["fade_seconds"] for x in shell.get("/api/looks").json()["looks"]] == [3.0] * 4


def test_an_unreadable_entry_in_looks_json_is_neither_overwritten_nor_fatal(hand_edited):
    saved = hand_edited.post("/api/looks", json={"name": "Night"})
    assert saved.status_code == 200, saved.text
    new_id = saved.json()["look"]["id"]
    assert new_id != "night"
    with hand_edited.websocket_connect(WS) as ws:
        ws.receive_json(), ws.receive_json()  # hello, look
        ws.send_json({"type": "looks.delete", "id": new_id})
        while ws.receive_json()["type"] != "store":
            pass
    assert json.loads(hand_edited.file.read_text(encoding="utf-8")) == HAND_EDITED  # the hand-made entries are as they were


def test_a_look_that_cannot_be_worked_out_moves_no_light_and_sets_no_look(shell):
    look = _save_three(shell, "Slow", 2)
    fixtures = shell.hub.fixtures
    ids = {n: _lights(shell)[n]["id"] for n in THREE}
    before = {n: fixtures[i].state for n, i in ids.items()}
    fixtures[ids["Backlight"]].caps = None  # the last light's model data is unusable, whatever the cause
    with pytest.raises(Exception):
        shell.post(f"/api/looks/{look}/apply")
    for name in ("Key light", "Fill"):
        assert fixtures[ids[name]].engine.kind is None and fixtures[ids[name]].state == before[name], name
    assert shell.hub.look is None


def test_a_light_off_the_network_is_left_alone_and_all_off_does_not_claim_it_is_off(shell):
    look = _save_three(shell, "Talking head", 0)
    ids = {n: _lights(shell)[n]["id"] for n in THREE}
    away = shell.hub.fixtures[ids["Backlight"]]
    mesh = away.light.network
    away.light = dataclasses.replace(away.light, network="0000ffff")  # saved on another mesh: out of reach
    away.stream_source = "music"
    before = away.state

    applied = shell.post(f"/api/looks/{look}/apply")
    assert applied.status_code == 200 and applied.json()["skipped"] == [away.id]
    assert away.state == before and away.stream_source == "music"
    assert _lights(shell)["Key light"]["state"]["brightness"] == THREE["Key light"]

    only_away = shell.post("/api/looks", json={"name": "Away", "lights": {away.id: {"brightness": 5}}}).json()["look"]["id"]
    refused = shell.post(f"/api/looks/{only_away}/apply")
    assert refused.status_code == 409 and refused.json()["error"] == "look_has_no_lights"

    off = shell.post("/api/all-off")
    assert off.json() == {"ok": True, "skipped": [away.id]}
    assert away.state.power and away.stream_source == "music"
    assert shell.hub.look == {"id": look, "name": "Talking head"}  # a light is still on, so no "all off"
    assert not any(l["state"]["power"] for n, l in _lights(shell).items() if l["id"] != away.id)

    away.light = dataclasses.replace(away.light, network=mesh)  # back on the mesh
    assert shell.post("/api/all-off").json() == {"ok": True, "skipped": []}
    assert shell.hub.look is None and not away.state.power
