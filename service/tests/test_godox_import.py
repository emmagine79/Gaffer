"""Importing the Godox app's mesh export through the WebSocket, against the demo studio."""

from __future__ import annotations

import asyncio
import base64
import json
import sqlite3
import threading

import pytest
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from fastapi.testclient import TestClient
from godox_mesh_bt.crypto import k3

from gaffer import demo, godox_import
from gaffer.app import create_app
from gaffer.demo import DemoScanner
from gaffer.discovery import MESH_PROXY, Nearby
from gaffer.godox_import import light_plans, parse_mesh_export
from gaffer.hub import Client, Hub
from gaffer.lights import LightLibrary
from gaffer.link import LinkManager, Member, SequenceVault
from gaffer.store import Store

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


@pytest.mark.parametrize("cid", [529, "0x0211", "0211", " 0x0211 "])
def test_the_godox_company_id_may_be_written_as_a_number_or_with_0x(client, cid):
    nodes = [{**node, "cid": cid} if node.get("cid") == "0211" else node for node in MESH["nodes"]]
    _check_imported(client, _import(client, meshJson=json.dumps({**MESH, "nodes": nodes})))


def test_the_database_copy_is_closed_after_reading(monkeypatch, tmp_path):
    data = base64.b64decode(_db(tmp_path, MESH))
    opened = []
    real = sqlite3.connect
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: opened.append(real(*a, **k)) or opened[-1])
    godox_import.mesh_json_from_db(data)
    assert len(opened) == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        opened[0].execute("SELECT 1")


async def _studio(tmp_path, scanner=None):
    hub = Hub(Store(tmp_path), LightLibrary(tmp_path), demo=True, scanner=scanner or DemoScanner())
    await hub.start()
    return hub


async def test_reading_a_large_export_does_not_stall_the_event_loop(tmp_path, monkeypatch):
    """The parse waits here for the event loop to run another task. On the loop's own thread it would never get one."""
    loop_ran = threading.Event()
    parse = godox_import.mesh_import_from_message

    def waits_for_the_loop(message):
        assert loop_ran.wait(timeout=5), "the event loop was blocked while the export was read"
        return parse(message)

    monkeypatch.setattr("gaffer.hub.mesh_import_from_message", waits_for_the_loop)
    hub = await _studio(tmp_path)
    try:
        async def another_task():
            await asyncio.sleep(0)
            loop_ran.set()

        (lights, _), _ = await asyncio.gather(hub.import_godox(Client(), {"meshJson": json.dumps(MESH)}), another_task())
        assert len(lights) == 2
    finally:
        await hub.stop()


class _Scanner:
    """A scan that hears the given lights, the way macOS names them: by a UUID, not a Bluetooth address."""

    def __init__(self, *nearby):
        self.devices, self.busy, self._nearby = {}, False, nearby

    async def scan(self, seconds, on_found=None):
        for seen in self._nearby:
            on_found(seen)
        return list(self._nearby)


async def test_a_scan_after_an_import_finds_the_same_lights_and_adds_no_second_copy(tmp_path):
    network = k3(bytes.fromhex(MESH["netKeys"][0]["key"])).hex()
    heard = [Nearby(f"1B7E0C5A-0000-4000-8000-00000000000{n}", "GD_LED", -50, "mesh", None, network) for n in (1, 2)]
    hub = await _studio(tmp_path, _Scanner(*heard))
    try:
        for _ in range(2):  # the second time is the Godox app's export read again
            await hub.import_godox(Client(), {"meshJson": json.dumps(MESH)})
        found = await hub.scan(seconds=1)
        assert {n["relation"] for n in found} == {"your-network"} and len(found) == 2
        assert sorted(light.name for light in hub.library.lights) == ["Test fill", "Test key"]
    finally:
        await hub.stop()


async def test_the_link_picks_an_imported_lights_network_by_its_id_whatever_its_saved_address(tmp_path, monkeypatch):
    """The saved address is a stand-in or the app's own, never the UUID macOS reports; the network id still finds the light."""
    library = LightLibrary(tmp_path)
    imported = parse_mesh_export(json.dumps({**MESH, "nodes": [{k: v for k, v in MESH["nodes"][1].items() if k != "macAddress"}]}))
    for name, address, state in light_plans(imported):
        library.import_keys(state, address=address, name=name, source="unknown")
    light = library.lights[0]
    public_id = k3(bytes.fromhex(imported.network_key)).hex()
    uuid = "1B7E0C5A-0000-4000-8000-000000000001"

    class FakeBleakScanner:
        def __init__(self, detection_callback):
            self.callback = detection_callback

        async def __aenter__(self):
            advert = AdvertisementData("GD_LED", {}, {MESH_PROXY: bytes([0]) + bytes.fromhex(public_id) }, [MESH_PROXY], None, -48, ())
            self.callback(BLEDevice(uuid, "GD_LED", None), advert)

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr("bleak.BleakScanner", FakeBleakScanner)
    link = LinkManager(
        SequenceVault(library.network_path(light.network)),
        members=lambda: [Member(light.id, light.address, light.node_address)],
        public_id=public_id, preferred=lambda: light.address,
        on_connected=lambda _t: None, on_disconnected=lambda: None, serial=None, scan_timeout=2, prefer_wait=0,
    )
    device, member, rssi = await link._find_gateway()
    assert light.address != uuid and device.address == uuid and rssi == -48
