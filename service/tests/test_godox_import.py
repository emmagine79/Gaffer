"""Importing the Godox app's mesh export through the WebSocket, against the demo studio."""

from __future__ import annotations

import base64
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from gaffer import demo
from gaffer.app import create_app

# Invented keys, names and addresses. Nothing here belongs to a real light.
MESH = {
    "netKeys": [{"key": "ab" * 16, "index": 0}],
    "appKeys": [{"key": "cd" * 16, "index": 0, "boundNetKey": 0}],
    "nodes": [
        {"name": "Test provisioner", "unicastAddress": "0001"},  # the app itself: no cid
        {"name": "Test key", "cid": "0211", "unicastAddress": "0115", "deviceKey": "11" * 16,
         "macAddress": "020000000001"},
        {"name": "Test fill", "cid": "0211", "unicastAddress": "0117", "deviceKey": "22" * 16,
         "macAddress": "020000000002"},
        {"name": "Other vendor", "cid": "0059", "unicastAddress": "0119"},
    ],
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "PACE", 0.05)
    with TestClient(create_app(demo=True, data_dir=tmp_path)) as c:
        yield c


def _import(client, **fields):
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "lights.import", "rid": 7, **fields})
        for _ in range(400):
            message = ws.receive_json()
            if message.get("rid") == 7:
                return message
    raise AssertionError("no reply")


def _saved(client):
    with client.websocket_connect("/ws") as ws:
        return {light["name"]: light for light in ws.receive_json()["lights"]}


def _db(tmp_path, *meshes):
    path = tmp_path / "GodoxLight.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE Project (id INTEGER PRIMARY KEY, meshJson TEXT)")
        db.executemany("INSERT INTO Project (meshJson) VALUES (?)", [(json.dumps(m),) for m in meshes])
    return base64.b64encode(path.read_bytes()).decode()


def _check_imported(client, reply):
    assert reply["type"] == "ack" and len(reply["lights"]) == 2 and reply["skipped"] == []
    lights = _saved(client)
    assert lights["Test key"]["node_address"] == 0x0115 and lights["Test key"]["address"] == "02:00:00:00:00:01"
    assert lights["Test fill"]["node_address"] == 0x0117 and lights["Test fill"]["address"] == "02:00:00:00:00:02"
    assert "Test provisioner" not in lights and "Other vendor" not in lights


def test_pasted_mesh_json_saves_one_light_per_godox_node(client):
    _check_imported(client, _import(client, meshJson=json.dumps(MESH)))


def test_a_godox_light_db_gives_the_same_lights(client, tmp_path):
    _check_imported(client, _import(client, db=_db(tmp_path, {**MESH, "nodes": []}, MESH)))


@pytest.mark.parametrize(("fields", "reason"), [
    ({"meshJson": "this is not json"}, "not JSON"),
    ({"meshJson": json.dumps({"netKeys": [], "appKeys": [], "nodes": []})}, "no network key"),
    ({"meshJson": json.dumps({**MESH, "nodes": [MESH["nodes"][0]]})}, "No Godox lights found"),
    ({"db": base64.b64encode(b"not a database at all").decode()}, "not the Godox app's GodoxLight.db"),
    ({"db": "!!not base64!!"}, "did not arrive intact"),
])
def test_a_bad_or_foreign_file_is_refused_plainly_and_saves_nothing(client, tmp_path, fields, reason):
    before = _saved(client)
    reply = _import(client, **fields)
    assert reply["type"] == "error" and reason in reply["text"]
    assert not any(part in reply["text"] for part in ("/Users/", "/private/", "/var/", str(tmp_path)))
    assert _saved(client) == before


def test_a_database_from_another_app_is_refused(client, tmp_path):
    path = tmp_path / "other.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE Notes (body TEXT)")
    reply = _import(client, db=base64.b64encode(path.read_bytes()).decode())
    assert reply["type"] == "error" and "GodoxLight.db" in reply["text"] and "/" not in reply["text"].replace("GodoxLight.db", "")
