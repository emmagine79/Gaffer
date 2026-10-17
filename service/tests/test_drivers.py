"""Acceptance tests for SPEC-003: the driver contract, model files, and the Godox driver behind it.

Each test drives the real route: the running demo app (HTTP and WebSocket) or the Godox
driver's own apply(). Demo mode and a temp data folder, so no Bluetooth is touched.
"""

from __future__ import annotations

import asyncio
import json
import sys
import textwrap

import pytest
from fastapi.testclient import TestClient

from gaffer import demo, drivers
from gaffer.app import create_app
from gaffer.drivers.godox import GodoxDriver
from gaffer.lights import LightLibrary, SavedLight
from gaffer.state import Cct, LightState

# Access payloads (vendor opcode F01102 + Godox frame) the vendor app was captured sending, as recorded in
# godox-mesh-bt's tests (test_v2_commands.py, test_access_layer.py). Hardcoded: a changed byte must fail.
POWER_ON = "F01102FE00FFFFFFFFFF7F"
POWER_OFF = "F01102FE01FFFFFFFFFF48"
CCT_50_5600K = "F01102F032383200000032"
CCT_80_5600K = "F01102F05038320000009F"
CCT_50_3200K = "F01102F032203200000070"

BI_COLOUR = "003A"  # SL60IIBi: no tint, 2800-6500 K


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "PACE", 0.05)
    with TestClient(create_app(demo=True, data_dir=tmp_path)) as c:
        c.data_dir = tmp_path
        yield c


def _write(root, driver, name, body):
    folder = root / "models" / driver
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(body if isinstance(body, str) else json.dumps(body), encoding="utf-8")
    return path


def _model(model_id, driver="zhiyun", **extra):
    return {"id": model_id, "driver": driver, "brand": "Zhiyun", "name": "Test panel", "min_kelvin": 2700,
            "max_kelvin": 6500, "modes": ["cct"], "match": {"name_prefix": "PL1"}, "driver_data": {"op": 1}, **extra}


# -- AC 1: Godox bytes -------------------------------------------------------------------


async def test_godox_apply_writes_the_recorded_payloads_for_power_brightness_and_colour_temperature():
    light = SavedLight(id="l1", name="Fill", address="DE:MO:00:00:00:02", radio_id=BI_COLOUR, network="n", node_address=2)
    sent: list[tuple[str, int | None]] = []

    async def sender(frame: bytes, node: int | None) -> None:
        sent.append((_access(frame), node))

    driver = GodoxDriver(max_rate=1000)
    await driver.start()
    driver.attach_sender(sender)

    async def settle():
        for _ in range(60):
            await asyncio.sleep(0.005)

    try:
        for state in (
            LightState(power=True, brightness=50, mode="cct", cct=Cct(kelvin=5600)),
            LightState(power=True, brightness=80, mode="cct", cct=Cct(kelvin=5600)),
            LightState(power=True, brightness=50, mode="cct", cct=Cct(kelvin=3200)),
            LightState(power=False, brightness=50, mode="cct", cct=Cct(kelvin=3200)),
        ):
            driver.apply(light, state)
            await settle()
    finally:
        await driver.stop()

    assert [payload for payload, _ in sent] == [
        POWER_ON, CCT_50_5600K, CCT_80_5600K, CCT_50_3200K, POWER_OFF,
    ]
    assert {node for _, node in sent} == {2}


def _access(frame: bytes) -> str:
    from gaffer.drivers.godox import encode_access_payload

    return encode_access_payload(frame).hex().upper()


# -- AC 2: a dropped model file --------------------------------------------------------------


def test_a_model_file_in_the_models_folder_appears_in_the_catalogue_and_overrides_a_table_row(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "PACE", 0.05)
    _write(tmp_path, "zhiyun", "ZYTEST.json", _model("ZYTEST", match={"name_prefix": "PL1", "service": "0000fee9-0000-1000-8000-00805f9b34fb"}))
    _write(tmp_path, "godox", f"{BI_COLOUR}.json", _model(BI_COLOUR, "godox", brand="Godox", name="Corrected SL60"))
    with TestClient(create_app(demo=True, data_dir=tmp_path)) as c:
        listing = c.get("/api/models").json()
    by_id = {m["id"]: m for m in listing["models"]}
    assert by_id["ZYTEST"]["driver"] == "zhiyun" and by_id["ZYTEST"]["brand"] == "Zhiyun"
    assert by_id["ZYTEST"]["match"]["name_prefix"] == "PL1"
    # SPEC-006 reads ModelCaps.features from here: the keys the UI lays controls out from.
    assert {"white", "daylight", "colour", "channels", "tint", "gels", "builtin_effects", "fan", "battery",
            "smoothness", "control_modes"} == set(by_id["ZYTEST"]["features"])
    assert by_id[BI_COLOUR]["name"] == "Corrected SL60"  # same id as a table row: the file wins
    assert sum(1 for m in listing["models"] if m["id"] == BI_COLOUR) == 1
    assert listing["skipped"] == []


def test_a_bad_model_file_is_skipped_with_a_reason_and_changes_nothing(tmp_path, monkeypatch):
    """One bad file never stops the load (a good one beside them still appears); names are validated; an
    unreadable file does not replace the row it was meant to override; no reason shows a path."""
    monkeypatch.setattr(demo, "PACE", 0.05)
    _write(tmp_path, "zhiyun", "GOOD.json", _model("GOOD"))
    _write(tmp_path, "zhiyun", "BROKEN.json", "{ not json")
    _write(tmp_path, "zhiyun", "WRONGSTEM.json", _model("OTHER"))
    _write(tmp_path, "zhiyun", "CONSTRUCTOR.json", _model("constructor"))
    _write(tmp_path, "zhiyun", "DOTS.json", _model(".."))
    _write(tmp_path, "zhiyun", "PROTO.json", _model("__proto__"))
    _write(tmp_path, "zhiyun", "WRONGDRIVER.json", _model("WRONGDRIVER", "yongnuo"))
    _write(tmp_path, "zhiyun", "NEGATIVE.json", _model("NEGATIVE", min_kelvin=-5))
    _write(tmp_path, "zhiyun", "HUGE.json", _model("HUGE", note="x" * (2 << 20)))
    blocked = _write(tmp_path, "godox", f"{BI_COLOUR}.json", _model(BI_COLOUR, "godox", brand="Godox", name="Should not apply"))
    blocked.chmod(0)
    try:
        with TestClient(create_app(demo=True, data_dir=tmp_path)) as c:
            listing = c.get("/api/models").json()
    finally:
        blocked.chmod(0o644)
    ids = {m["id"] for m in listing["models"]}
    assert "GOOD" in ids
    assert not ids & {"BROKEN", "WRONGSTEM", "OTHER", "CONSTRUCTOR", "..", "__PROTO__", "WRONGDRIVER", "NEGATIVE", "HUGE"}
    assert next(m for m in listing["models"] if m["id"] == BI_COLOUR)["name"] != "Should not apply"
    skipped = {s["file"]: s["reason"] for s in listing["skipped"]}
    assert set(skipped) == {f"zhiyun/{n}.json" for n in (
        "BROKEN", "WRONGSTEM", "CONSTRUCTOR", "DOTS", "PROTO", "WRONGDRIVER", "NEGATIVE", "HUGE")} | {f"godox/{BI_COLOUR}.json"}
    text = json.dumps(listing)
    assert not any(bad in text for bad in ("/Users/", "/private/", "/var/", str(tmp_path)))


# -- AC 3: the hub commands lights through their driver ------------------------------------------


def test_setting_a_light_goes_to_the_driver_its_model_names(client):
    with client.websocket_connect("/ws") as ws:
        hello = ws.receive_json()
        lights = {light["name"]: light for light in hello["lights"]}
        zhiyun = lights["Zhiyun panel"]
        ws.send_json({"type": "select", "light": zhiyun["id"]})
        ws.send_json({"type": "set", "patch": {"brightness": 33}})
        for _ in range(200):
            m = ws.receive_json()
            if m["type"] == "state" and m["light"] == zhiyun["id"] and m["state"]["brightness"] == 33:
                break
        else:
            raise AssertionError("state never arrived")
    stand_in = client.app.state.hub.registry.get("demo")
    assert stand_in.applied[zhiyun["id"]].brightness == 33
    # and the Godox lights were not told: their driver is not the stand-in.
    assert lights["Key light"]["id"] not in stand_in.applied


# -- AC 4: three lights, one per driver, tagged by brand ------------------------------------------


def test_demo_seeds_one_light_per_driver_and_the_scan_tags_each_by_brand(client):
    with client.websocket_connect("/ws") as ws:
        hello = ws.receive_json()
    brands = {light["caps"]["brand"] for light in hello["lights"]}
    assert {"Godox", "Zhiyun", "Yongnuo"} <= brands
    yongnuo = next(light for light in hello["lights"] if light["caps"]["brand"] == "Yongnuo")
    assert yongnuo["channel"] == 1  # a Yongnuo light carries the channel it is set to
    families = {d["family"] for d in client.get("/api/scan?seconds=2").json()["devices"]}
    assert {"godox_mesh", "zhiyun", "yongnuo"} <= families


# -- the registry: a new folder plugs in -------------------------------------------------------------


def test_a_driver_folder_plugs_in_and_a_broken_one_is_skipped(tmp_path):
    brand = tmp_path / "fakebrand"
    brand.mkdir()
    (brand / "__init__.py").write_text(textwrap.dedent('''
        from gaffer.drivers.base import Driver

        class FakeDriver(Driver):
            id = "fakebrand"
            def match(self, advert): return "FAKE1" if advert.name == "FAKE" else None
            async def connect(self, light): ...
            def apply(self, light, state): ...
            async def identify(self, light): ...
            def status(self, light): return {"reachable": True, "held": False}
    '''))
    broken = tmp_path / "brokenbrand"
    broken.mkdir()
    (broken / "__init__.py").write_text("raise RuntimeError('boom')\n")
    drivers.__path__.append(str(tmp_path))
    try:
        registry = drivers.build_drivers()
        assert {"godox", "fakebrand"} <= set(registry.drivers)
        assert registry.match(drivers.Advert(address="A", name="FAKE")) == (registry.drivers["fakebrand"], "FAKE1")
        assert registry.skipped == [{"driver": "brokenbrand", "reason": "could not be imported"}]
    finally:
        drivers.__path__.remove(str(tmp_path))
        for name in [n for n in sys.modules if n.startswith(("gaffer.drivers.fakebrand", "gaffer.drivers.brokenbrand"))]:
            del sys.modules[name]


def test_a_lights_channel_survives_save_and_load(tmp_path):
    library = LightLibrary(tmp_path)
    network = library.create_network()
    light = library.add_paired(network_id=network, address="DE:MO:00:00:00:99", radio_id="YN-DEMO", node_address=2,
                               num_elements=1, device_key="")
    import dataclasses

    library.save_light(dataclasses.replace(light, channel=7))
    assert LightLibrary(tmp_path).get(light.id).channel == 7
