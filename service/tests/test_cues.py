"""SPEC-014 acceptance tests: cue lists, through the running app in demo mode (no Bluetooth).

Reached the way the Mac shell reaches it: behind the Host check and the session secret, signed in by
the cookie alone. A fake clock stands in for each light's clock so a 5 s fade needs no 5 s wait.
"""

from __future__ import annotations

import dataclasses
import json
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


#: A cues.json somebody edited by hand: an entry whose steps are not a list.
DAMAGED = [{"id": "interview", "name": "Interview", "steps": "oops"}]


@pytest.fixture
def hand_edited(tmp_path):
    (tmp_path / "cues.json").write_text(json.dumps(DAMAGED), encoding="utf-8")
    app = create_app(demo=True, data_dir=tmp_path)
    with TestClient(protect(app, SECRET), base_url="http://127.0.0.1", cookies={COOKIE: SECRET}) as client:
        client.hub = app.state.hub  # type: ignore[attr-defined]
        client.file = tmp_path / "cues.json"  # type: ignore[attr-defined]
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
           {"name": "ok", "steps": []},
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


def test_a_cue_can_be_edited_whatever_its_name_and_has_no_step_limit(shell):
    """Ids made from names such as Constructor, or from an 80 character name saved twice, stay editable."""
    wide, *_ = _three_looks(shell)
    step = {"look_id": wide, "fade_seconds": None}
    long_name = "x" * 80
    ids = []
    with shell.websocket_connect(WS) as ws:
        for name in ("Constructor", "Prototype", "Active", long_name, long_name):
            saved = _save_cue(ws, {"name": name, "steps": [step]})
            assert saved["type"] == "ack", (name, saved)
            edited = _save_cue(ws, {"id": saved["cue"]["id"], "name": name, "steps": [step, step]})
            assert edited["type"] == "ack", (name, edited)
            ids.append(saved["cue"]["id"])
        many = _save_cue(ws, {"name": "Long show", "steps": [step] * 201})
    assert many["type"] == "ack", many
    assert len(set(ids)) == 5 and "active" not in ids and all(len(i) <= 80 for i in ids)


def test_an_unreadable_entry_in_cues_json_is_neither_overwritten_nor_fatal(hand_edited):
    wide, *_ = _three_looks(hand_edited)
    with hand_edited.websocket_connect(WS) as ws:
        saved = _save_cue(ws, {"name": "Interview", "steps": [{"look_id": wide, "fade_seconds": None}]})
        assert saved["type"] == "ack", saved
        assert saved["cue"]["id"] != "interview"
        ws.send_json({"type": "cues.delete", "id": saved["cue"]["id"], "rid": 3})
        while ws.receive_json().get("type") != "store":
            pass
    assert json.loads(hand_edited.file.read_text(encoding="utf-8")) == DAMAGED  # the hand-made entry is as it was


def _delete_look(client, look_id):
    with client.websocket_connect(WS) as ws:
        ws.send_json({"type": "looks.delete", "id": look_id})  # no answer of its own: the store message follows
        while (m := ws.receive_json()).get("type") != "store" or m.get("collection") != "looks":
            pass


def _start(client, cue):
    with client.websocket_connect(WS) as ws:
        ws.send_json({"type": "cue.start", "id": cue, "rid": 5})
        while (m := ws.receive_json()).get("rid") != 5:
            pass
    assert m["type"] == "ack", m


def _light(client, name):
    return next(light for light in client.get("/api/lights").json()["lights"] if light["name"] == name)


def test_go_passes_over_a_look_that_is_gone_or_has_no_saved_light(shell):
    wide, close, warm = _three_looks(shell)
    cue = _cue(shell, [{"look_id": wide, "fade_seconds": None}, {"look_id": close, "fade_seconds": None},
                       {"look_id": warm, "fade_seconds": None}])
    _start(shell, cue)
    assert shell.post("/api/cues/active/go").json()["look"]["id"] == wide
    _delete_look(shell, close)
    third = shell.post("/api/cues/active/go")
    assert third.status_code == 200 and third.json()["look"]["id"] == warm and third.json()["cue"]["step"] == 3

    # A look written with only lights that are no longer saved (a hand edit) is passed over the same way.
    shell.hub.store.upsert("looks", {"id": "ghost", "name": "Ghost", "fade_seconds": 0.0, "lights": {"not-a-saved-light": {"power": True}}})
    ghost_cue = _cue(shell, [{"look_id": "ghost", "fade_seconds": None}, {"look_id": warm, "fade_seconds": None}], name="Ghost then warm")
    first = shell.post(f"/api/cues/{ghost_cue}/go")
    assert first.status_code == 200 and first.json()["look"]["id"] == warm


def test_go_fails_and_stays_put_when_the_next_look_s_lights_cannot_be_reached(shell):
    key, fill = _light(shell, "Key light"), _light(shell, "Fill")
    on_key = shell.post("/api/looks", json={"name": "On key", "fade_seconds": 0, "lights": {key["id"]: {"power": True, "brightness": 30.0}}}).json()["look"]["id"]
    on_fill = shell.post("/api/looks", json={"name": "On fill", "fade_seconds": 0, "lights": {fill["id"]: {"power": True, "brightness": 70.0}}}).json()["look"]["id"]
    cue = _cue(shell, [{"look_id": on_key, "fade_seconds": None}, {"look_id": on_fill, "fade_seconds": None}])
    _start(shell, cue)
    fixture = shell.hub.fixtures[key["id"]]
    mesh = fixture.light.network
    fixture.light = dataclasses.replace(fixture.light, network="0000ffff")  # saved on another mesh: out of reach
    fill_before = _light(shell, "Fill")["state"]

    refused = shell.post("/api/cues/active/go")
    assert refused.status_code == 409 and refused.json()["error"] == "lights_unreachable", refused.text
    assert _light(shell, "Fill")["state"] == fill_before and shell.hub.look is None  # the second look did not run instead

    assert "Key light" in refused.json()["message"]  # the person is told which light

    # The cue is stuck on that step until the person chooses: a page that connects is told (blocked), Go only
    # retries and fails again, and Skip moves past the step without applying it.
    with shell.websocket_connect(WS) as ws:
        told = [ws.receive_json() for _ in range(3)]  # hello, look, cue
        assert "Key light" in next(m for m in told if m["type"] == "cue")["blocked"]
        assert shell.post("/api/cues/active/go").status_code == 409
        ws.send_json({"type": "cue.skip", "rid": 6})
        while (m := ws.receive_json()).get("rid") != 6:
            pass
    assert m["type"] == "ack" and m["cue"]["step"] == 1 and m["cue"]["blocked"] is None
    assert shell.hub.look is None  # skipping applied nothing
    second = shell.post("/api/cues/active/go")
    assert second.status_code == 200 and second.json()["look"]["id"] == on_fill and second.json()["cue"]["step"] == 2

    # Without a skip, a light that comes back lets the same step run.
    _start(shell, cue)
    assert shell.post("/api/cues/active/go").status_code == 409
    fixture.light = dataclasses.replace(fixture.light, network=mesh)
    again = shell.post("/api/cues/active/go")
    assert again.status_code == 200 and again.json()["look"]["id"] == on_key and again.json()["cue"]["step"] == 1


def test_a_go_for_another_cue_that_fails_leaves_the_active_cue_alone(shell):
    wide, close, _ = _three_looks(shell)
    running = _cue(shell, [{"look_id": wide, "fade_seconds": None}, {"look_id": wide, "fade_seconds": None}], name="Running")
    broken = _cue(shell, [{"look_id": close, "fade_seconds": None}], name="Broken")
    _start(shell, running)
    assert shell.post("/api/cues/active/go").json()["cue"]["step"] == 1
    _delete_look(shell, close)

    refused = shell.post(f"/api/cues/{broken}/go")
    assert refused.status_code == 409 and refused.json()["error"] == "cue_steps_gone"
    next_step = shell.post("/api/cues/active/go")  # still the cue that was running, still at step 1
    assert next_step.status_code == 200 and next_step.json()["cue"] == {"id": running, "name": "Running", "step": 2, "steps": 2, "next": None, "blocked": None}


def test_saving_the_active_cue_keeps_its_place_unless_a_step_that_has_run_changed(shell):
    a, b, c = _three_looks(shell)
    d = _save_look(shell, "Cool", 80.0, 0)
    step = lambda look, fade=None: {"look_id": look, "fade_seconds": fade}  # noqa: E731
    cue = _cue(shell, [step(a), step(b), step(c), step(d)])
    _start(shell, cue)
    for _ in range(2):
        shell.post("/api/cues/active/go")  # a and b have run

    with shell.websocket_connect(WS) as ws:
        # Rename it and change a step still to come: the next Go is still step 3.
        assert _save_cue(ws, {"id": cue, "name": "Renamed", "steps": [step(a), step(b), step(c), step(d, 4)]})["type"] == "ack"
    third = shell.post("/api/cues/active/go")
    assert third.json()["look"]["id"] == c and third.json()["cue"]["step"] == 3

    # Remove step 1: what has run is no longer what it was, so the cue goes back to the top, not on to step 3.
    with shell.websocket_connect(WS) as ws:
        assert _save_cue(ws, {"id": cue, "name": "Renamed", "steps": [step(b), step(c), step(d, 4)]})["type"] == "ack"
    top = shell.post("/api/cues/active/go")
    assert top.json()["look"]["id"] == b and top.json()["cue"]["step"] == 1


def test_the_cue_message_names_the_look_the_next_go_runs(shell):
    wide, close, warm = _three_looks(shell)
    cue = _cue(shell, [{"look_id": wide, "fade_seconds": None}, {"look_id": close, "fade_seconds": None},
                       {"look_id": warm, "fade_seconds": None}])
    _start(shell, cue)
    shell.post("/api/cues/active/go")
    with shell.websocket_connect(WS) as ws:
        ws.send_json({"type": "looks.delete", "id": close})  # the look of step 2 goes while the cue is on step 1
        ws.send_json({"type": "cue.back", "rid": 9})  # refused at the first step; its answer marks the end of the frames above
        seen = []
        while (m := ws.receive_json()).get("rid") != 9:
            seen.append(m)
    frames = [m for m in seen if m["type"] == "cue"]
    assert frames and frames[-1]["next"] == {"id": warm, "name": "Warm"} and frames[-1]["step"] == 1
    assert shell.post("/api/cues/active/go").json()["look"]["id"] == warm  # and that is the look Go runs


def test_the_cue_message_follows_a_light_that_is_forgotten_and_back_stops_at_the_first_runnable_step(shell):
    key, fill = _light(shell, "Key light"), _light(shell, "Fill")
    on_key = shell.post("/api/looks", json={"name": "On key", "fade_seconds": 0, "lights": {key["id"]: {"power": True, "brightness": 30.0}}}).json()["look"]["id"]
    on_fill = shell.post("/api/looks", json={"name": "On fill", "fade_seconds": 0, "lights": {fill["id"]: {"power": True, "brightness": 70.0}}}).json()["look"]["id"]
    on_both = shell.post("/api/looks", json={"name": "Both", "fade_seconds": 0, "lights": {
        key["id"]: {"power": True, "brightness": 10.0}, fill["id"]: {"power": True, "brightness": 10.0}}}).json()["look"]["id"]
    cue = _cue(shell, [{"look_id": on_key, "fade_seconds": None}, {"look_id": on_fill, "fade_seconds": None},
                       {"look_id": on_both, "fade_seconds": None}])
    _start(shell, cue)
    with shell.websocket_connect(WS) as ws:
        # The only light of the first step is forgotten: the label must name step 2, which Go will run.
        ws.send_json({"type": "lights.forget", "light": key["id"]})
        frames = []
        while not frames or frames[-1]["next"] != {"id": on_fill, "name": "On fill"}:
            m = ws.receive_json()
            if m["type"] == "cue":
                frames.append(m)
        assert _go(ws)["look"]["id"] == on_fill
        assert _go(ws)["look"]["id"] == on_both
        # Back from step 3 goes to step 2; step 1 is gone, so from step 2 there is nothing earlier.
        assert _go(ws, "cue.back")["look"]["id"] == on_fill
        refused = _go(ws, "cue.back")
        assert refused["type"] == "error" and refused["text"] == "Already at the first step."
