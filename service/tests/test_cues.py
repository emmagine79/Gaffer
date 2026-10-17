"""SPEC-014 acceptance tests: cue lists, through the running app in demo mode (no Bluetooth).

Reached the way the Mac shell reaches it: behind the Host check and the session secret, signed in by
the cookie alone. A fake clock stands in for each light's clock so a 5 s fade needs no 5 s wait.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from gaffer.app import create_app
from gaffer.session import COOKIE, protect

SECRET = "test-secret-for-cues"
WS = "ws://127.0.0.1/ws"


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def shell(tmp_path):
    app = create_app(demo=True, data_dir=tmp_path)
    with TestClient(protect(app, SECRET), base_url="http://127.0.0.1", cookies={COOKIE: SECRET}) as client:
        client.hub = app.state.hub  # type: ignore[attr-defined]
        client.clock = FakeClock()  # type: ignore[attr-defined]
        for fixture in client.hub.fixtures.values():
            fixture.engine._clock = client.clock
        yield client


def _wait(predicate, what, seconds=5.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError(f"never happened: {what}")


def _key(client):
    return next(light for light in client.get("/api/lights").json()["lights"] if light["name"] == "Key light")


def _save_look(client, name, brightness, fade):
    key = _key(client)
    reply = client.post("/api/looks", json={"name": name, "fade_seconds": fade,
                                            "lights": {key["id"]: {"power": True, "brightness": brightness}}})
    assert reply.status_code == 200, reply.text
    return reply.json()["look"]["id"]


def _three_looks(client):
    """Look fades 0, 5 and 0, so a step's own fade must be seen to override, and a missing one to fall back."""
    return [_save_look(client, "Wide", 20.0, 0), _save_look(client, "Close", 40.0, 5), _save_look(client, "Warm", 60.0, 0)]


def _save_cue(ws, cue):
    ws.send_json({"type": "cues.save", "cue": cue, "rid": 1})
    while (m := ws.receive_json()).get("rid") != 1:
        pass
    return m


def _cue(shell, steps, name="Interview"):
    with shell.websocket_connect(WS) as ws:
        reply = _save_cue(ws, {"name": name, "steps": steps})
    assert reply["type"] == "ack", reply
    return reply["cue"]["id"]


def _go(ws, what="cue.go"):
    ws.send_json({"type": what, "rid": 9})
    while (m := ws.receive_json()).get("rid") != 9:
        pass
    return m


def test_ac6_go_applies_the_looks_in_order_with_the_step_fade_over_the_look_fade(shell):
    wide, close, warm = _three_looks(shell)
    cue = _cue(shell, [{"look_id": wide, "fade_seconds": 2}, {"look_id": close, "fade_seconds": None},
                       {"look_id": warm, "fade_seconds": None}])
    # A fresh cue sits at the top: nothing has run, so the first Go applies the first look.
    with shell.websocket_connect(WS) as ws:
        ws.receive_json()
        ws.send_json({"type": "cue.start", "id": cue, "rid": 5})
        while ws.receive_json().get("rid") != 5:
            pass
        assert shell.hub.look is None

        # Step 1: the look's fade is 0 but the step says 2, so it is a 2 s transition on the Key light.
        first = _go(ws)
        assert first["look"] == {"id": wide, "name": "Wide"} and first["cue"]["step"] == 1 and first["cue"]["steps"] == 3
        assert _key(shell)["engine"]["kind"] == "transition" and _key(shell)["engine"]["duration"] == 2
        shell.clock.now += 3
        _wait(lambda: _key(shell)["state"]["brightness"] == 20.0, "step 1 ending on its look")

        # Step 2 through the Mac shell's route: no step fade, so the look's own 5 s is used.
        second = shell.post("/api/cues/active/go")
        assert second.status_code == 200 and second.json()["look"] == {"id": close, "name": "Close"}
        assert _key(shell)["engine"]["kind"] == "transition" and _key(shell)["engine"]["duration"] == 5
        shell.clock.now += 6
        _wait(lambda: _key(shell)["state"]["brightness"] == 40.0, "step 2 ending on its look")

        # Step 3: no step fade and a look fade of 0 means the light is set at once.
        third = _go(ws)
        assert third["look"] == {"id": warm, "name": "Warm"}
        assert _key(shell)["engine"]["kind"] is None and _key(shell)["state"]["brightness"] == 60.0

        # The end of the list: Go says so and changes nothing.
        end = shell.post("/api/cues/active/go")
        assert end.status_code == 409 and end.json()["error"] == "cue_finished"
        assert shell.hub.look["id"] == warm

        # Back steps to the look before the last one that ran; at the first step it refuses.
        back = _go(ws, "cue.back")
        assert back["look"]["id"] == close and back["cue"]["step"] == 2
        assert _go(ws, "cue.back")["look"]["id"] == wide
        assert _go(ws, "cue.back")["type"] == "error"

        # The page is told the cue and step as they change.
        ws.send_json({"type": "cue.go"})
        seen = []
        while not any(m["type"] == "cue" and m["step"] == 2 for m in seen):
            seen.append(ws.receive_json())


def test_post_cues_go_from_loopback_advances_the_cue(shell):
    wide, close, _ = _three_looks(shell)
    cue = _cue(shell, [{"look_id": wide, "fade_seconds": None}, {"look_id": close, "fade_seconds": 0}])
    # The shell's route with no cue running: a refusal it can show, and nothing moves.
    refused = shell.post("/api/cues/active/go")
    assert refused.status_code == 409 and refused.json()["error"] == "no_active_cue" and shell.hub.look is None
    assert shell.post("/api/cues/nope/go").status_code == 404
    # An id starts that cue and goes to its first step; 'active' then means that cue.
    first = shell.post(f"/api/cues/{cue}/go")
    assert first.status_code == 200 and first.json()["ok"] is True and first.json()["look"]["id"] == wide
    second = shell.post("/api/cues/active/go")
    assert second.status_code == 200 and second.json()["look"]["id"] == close and second.json()["cue"]["step"] == 2
    # A page on another port cannot move the cue (the non-GET Origin check), and the answer holds no path.
    for origin in ("http://127.0.0.1:9", "http://evil.example", "null"):
        blocked = shell.post(f"/api/cues/{cue}/go", headers={"origin": origin})
        assert blocked.status_code == 403 and blocked.json()["error"] == "origin_not_allowed", origin
    assert shell.hub.cue["step"] == 2
    # Without the cookie it does not work.
    shell.cookies.clear()
    assert shell.post("/api/cues/active/go").status_code == 401


def test_a_refused_cue_save_says_why_and_stores_nothing(shell):
    wide, *_ = _three_looks(shell)
    good = {"look_id": wide, "fade_seconds": None}
    bad = ({"name": " ", "steps": [good]}, {"name": "x" * 81, "steps": [good]}, {"name": "a\nb", "steps": [good]},
           {"name": "ok", "steps": []}, {"name": "ok", "steps": [good] * 201},
           {"name": "ok", "steps": [{"look_id": "nope", "fade_seconds": None}]},
           {"name": "ok", "steps": [{"look_id": wide, "fade_seconds": 61}]},
           {"name": "ok", "steps": [{"look_id": wide, "fade_seconds": True}]},
           {"name": "ok", "id": "active", "steps": [good]}, {"name": "ok", "id": "constructor", "steps": [good]},
           {"name": "ok", "id": "../x", "steps": [good]})
    with shell.websocket_connect(WS) as ws:
        for cue in bad:
            reply = _save_cue(ws, cue)
            assert reply["type"] == "error", cue
            assert not any(p in reply["text"] for p in ("/Users/", "/private/", "/var/", "Traceback")), reply
        ws.send_json({"type": "store.upsert", "collection": "cues", "item": {"name": "sneaky"}, "rid": 2})
        while (m := ws.receive_json()).get("rid") != 2:
            pass
        assert m["type"] == "error"
    assert shell.hub.store.items("cues") == []
