"""Who may drive the studio, and what it refuses to save."""

from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from gaffer import demo
from gaffer.app import create_app
from gaffer.guard import LOCAL_HOSTS, hostname, origin_allowed
from gaffer.store import Store

# -- the rules ----------------------------------------------------------------------------


@pytest.mark.parametrize(("header", "name"), [
    ("127.0.0.1:8787", "127.0.0.1"), ("localhost", "localhost"), ("[::1]:8787", "::1"), ("Evil.Example:80", "evil.example"),
])
def test_host_headers_are_read_without_their_port(header, name):
    assert hostname(header) == name


def test_only_the_studios_own_page_may_open_a_socket():
    assert origin_allowed("http://127.0.0.1:8787", "127.0.0.1:8787", LOCAL_HOSTS)
    assert origin_allowed(None, "127.0.0.1:8787", LOCAL_HOSTS)  # not a browser
    assert not origin_allowed("https://evil.example", "127.0.0.1:8787", LOCAL_HOSTS)
    assert not origin_allowed("http://127.0.0.1:9999", "127.0.0.1:8787", LOCAL_HOSTS)  # another local app
    # DNS rebinding: the page and the Host agree, but the name is not this machine's
    assert not origin_allowed("http://evil.example:8787", "evil.example:8787", LOCAL_HOSTS)


# -- the app ---------------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "PACE", 0.05)
    with TestClient(create_app(demo=True, data_dir=tmp_path)) as c:
        yield c


def test_a_socket_from_another_site_is_refused(client):
    with pytest.raises(WebSocketDisconnect) as refused,             client.websocket_connect("/ws", headers={"origin": "https://evil.example"}) as ws:
        ws.receive_json()
    assert refused.value.code == 4403


def test_a_socket_from_the_studio_page_is_accepted(client):
    with client.websocket_connect("/ws", headers={"origin": "http://testserver"}) as ws:
        assert ws.receive_json()["type"] == "hello"


def test_requests_for_a_foreign_host_name_are_refused(client):
    assert client.get("/api/health", headers={"host": "evil.example"}).status_code == 421
    assert client.get("/api/health").status_code == 200


def test_the_lan_token_guards_health_for_other_machines(tmp_path):
    app = create_app(demo=True, data_dir=tmp_path, token="secret", hosts=("192.168.1.20",))
    with TestClient(app, client=("192.168.1.50", 5000)) as remote:
        assert remote.get("/api/health", headers={"host": "192.168.1.20:8787"}).status_code == 401
        assert remote.get("/api/health?t=secret", headers={"host": "192.168.1.20:8787"}).status_code == 200


# -- what is never saved ---------------------------------------------------------------------


def _until(ws, predicate, limit=300):
    for _ in range(limit):
        m = ws.receive_json()
        if predicate(m):
            return m
    raise AssertionError("never arrived")


@pytest.mark.parametrize("patch", [{"max_rate": 0}, {"sync_interval": "fast"}, {"relay_ttl": 1000}, {"favorites": "x"}])
def test_settings_out_of_range_are_refused(client, patch):
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "settings", "patch": patch, "rid": 1})
        assert _until(ws, lambda m: m.get("rid") == 1)["type"] == "error"


def test_a_bad_settings_file_falls_back_to_defaults(tmp_path):
    (tmp_path / "settings.json").write_text(json.dumps({"max_rate": 0, "sync_interval": "x", "default_fade": 2}), encoding="utf-8")
    settings = Store(tmp_path).settings
    assert settings["max_rate"] == 40.0 and settings["sync_interval"] == 0.7 and settings["default_fade"] == 2.0


GOOD_KEYS = {"network_key": "ab" * 16, "app_key": "cd" * 16, "provisioner_address": 1, "node_address": 2,
             "sequence_number": 10, "iv_index": 0}


@pytest.mark.parametrize(("keys", "address"), [
    ({**GOOD_KEYS, "network_key": "zz" * 16}, "AA:BB:CC:DD:EE:01"),
    ({**GOOD_KEYS, "node_address": 0x9000}, "AA:BB:CC:DD:EE:01"),
    ({**GOOD_KEYS, "num_elements": 10**9}, "AA:BB:CC:DD:EE:01"),
    (GOOD_KEYS, "not an address"),
])
def test_unusable_keys_are_refused_before_anything_is_saved(client, tmp_path, keys, address):
    with client.websocket_connect("/ws") as ws:
        hello = ws.receive_json()
        ws.send_json({"type": "lights.import", "keys": keys, "address": address, "rid": 2})
        assert _until(ws, lambda m: m.get("rid") == 2)["type"] == "error"
    lights = json.loads((tmp_path / "lights.json").read_text(encoding="utf-8"))["lights"]
    assert len(lights) == len(hello["lights"])


def test_pairing_needs_a_light_the_studio_itself_found(client):
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "lights.pair", "address": "11:22:33:44:55:66", "rid": 3})
        assert "scan first" in _until(ws, lambda m: m.get("rid") == 3)["text"]


def test_a_long_scan_does_not_hold_up_the_sliders(client):
    with client.websocket_connect("/ws") as ws:
        key = ws.receive_json()["selected"]
        ws.send_json({"type": "lights.scan", "seconds": 4, "rid": 4})
        started = time.monotonic()
        ws.send_json({"type": "set", "light": key, "patch": {"brightness": 23}})
        _until(ws, lambda m: m["type"] == "state" and m["light"] == key and m["state"]["brightness"] == 23)
        assert time.monotonic() - started < 1.5  # answered while the scan still runs
        _until(ws, lambda m: m.get("rid") == 4)
