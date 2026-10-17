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
from gaffer import hub as hub_module
from gaffer.app import create_app
from gaffer.catalog import configure_models
from gaffer.drivers.base import Driver
from gaffer.drivers.godox import GodoxDriver
from gaffer.hub import Hub
from gaffer.lights import LightLibrary, SavedLight
from gaffer.state import Cct, LightState
from gaffer.store import Store

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

    async def until(count):
        for _ in range(1000):
            if len(sent) >= count:
                return
            await asyncio.sleep(0.005)
        raise AssertionError(f"only {len(sent)} of {count} writes arrived")

    try:
        # Each state writes: power on + 50% at 5600 K, then one write per change, then power off.
        for state, writes in (
            (LightState(power=True, brightness=50, mode="cct", cct=Cct(kelvin=5600)), 2),
            (LightState(power=True, brightness=80, mode="cct", cct=Cct(kelvin=5600)), 3),
            (LightState(power=True, brightness=50, mode="cct", cct=Cct(kelvin=3200)), 4),
            (LightState(power=False, brightness=50, mode="cct", cct=Cct(kelvin=3200)), 5),
        ):
            driver.apply(light, state)
            await until(writes)
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
    blocked = _write(tmp_path, "godox", f"{BI_COLOUR}.json", _model(BI_COLOUR, "godox", brand="Godox", name="Should not apply"))
    blocked.chmod(0)
    try:
        with TestClient(create_app(demo=True, data_dir=tmp_path)) as c:
            listing = c.get("/api/models").json()
    finally:
        blocked.chmod(0o644)
    ids = {m["id"] for m in listing["models"]}
    assert "GOOD" in ids
    assert not ids & {"BROKEN", "WRONGSTEM", "OTHER", "CONSTRUCTOR", "..", "__PROTO__", "WRONGDRIVER", "NEGATIVE"}
    assert next(m for m in listing["models"] if m["id"] == BI_COLOUR)["name"] != "Should not apply"
    skipped = {s["file"]: s["reason"] for s in listing["skipped"]}
    assert set(skipped) == {f"zhiyun/{n}.json" for n in (
        "BROKEN", "WRONGSTEM", "CONSTRUCTOR", "DOTS", "PROTO", "WRONGDRIVER", "NEGATIVE")} | {f"godox/{BI_COLOUR}.json"}
    text = json.dumps(listing)
    assert not any(bad in text for bad in ("/Users/", "/private/", "/var/", str(tmp_path)))


def test_reset_steps_reach_the_page_and_a_bad_value_is_refused(tmp_path, monkeypatch):
    """Friction items 2 to 4: the page reads each model's reset steps from the hello `models` list and GET
    /api/models. A Godox table row gets its sourced steps, a model file's own steps win, a model with no source
    has none, and a model file whose steps are not a list of words is skipped with a plain reason."""
    monkeypatch.setattr(demo, "PACE", 0.05)
    _write(tmp_path, "zhiyun", "OWNSTEPS.json", _model("OWNSTEPS", reset_steps=["Hold the button.", "Let go."], reset_source="its manual"))
    _write(tmp_path, "zhiyun", "BADSTEPS.json", _model("BADSTEPS", reset_steps="hold the button"))
    _write(tmp_path, "zhiyun", "EMPTYSTEP.json", _model("EMPTYSTEP", reset_steps=["Hold it.", " "]))
    with TestClient(create_app(demo=True, data_dir=tmp_path)) as c:
        listing = c.get("/api/models").json()
        with c.websocket_connect("/ws") as ws:
            hello = ws.receive_json()
            while hello["type"] != "hello":
                hello = ws.receive_json()
    for rows in (listing["models"], hello["models"]):
        by_id = {m.get("id") or m["radio_id"]: m for m in rows}
        assert by_id["OWNSTEPS"]["reset_steps"] == ["Hold the button.", "Let go."]
        assert "Press and hold the Bluetooth button for about 2 seconds." in by_id["0022"]["reset_steps"]  # LA150Bi
        assert by_id["0066"]["reset_steps"] == []  # ML100Bi: no source, so the page shows its generic line
        assert not {"BADSTEPS", "EMPTYSTEP"} & set(by_id)
    skipped = {s["file"]: s["reason"] for s in listing["skipped"]}
    assert skipped == {
        "zhiyun/BADSTEPS.json": "reset_steps must be a list of steps, each in words",
        "zhiyun/EMPTYSTEP.json": "reset_steps must be a list of steps, each in words",
    }


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


# -- the hub hands lights between drivers, and never to the wrong brand ------------------------------


@pytest.fixture
def demo_models():
    configure_models([], demo.DEMO_MODELS)  # what create_app does in demo mode
    yield
    configure_models()


async def _studio(tmp_path, *, orphan_model=None):
    """A demo hub over a seeded library: four Godox lights (nodes 2, 4, 6, 8), a Zhiyun and a Yongnuo stand-in."""
    library = LightLibrary(tmp_path)
    demo.seed(library)
    if orphan_model:
        library.add_paired(network_id=library.lights[0].network, address="DE:MO:00:00:00:77", radio_id=orphan_model,
                           node_address=40, num_elements=1, device_key="", name="Orphan")
    hub = Hub(Store(tmp_path), library, demo=True, scanner=demo.DemoScanner())
    await hub.start()
    for _ in range(400):
        if hub.controller is not None:
            return hub
        await asyncio.sleep(0.01)
    raise AssertionError("never connected")


def _light(hub, name):
    return next(f for f in hub.fixtures.values() if f.light.name == name)


class _Wire:
    """Stands in for the mesh link: records the node of every frame the Godox pump writes."""

    def __init__(self, hub):
        self.nodes: list[int | None] = []
        hub.godox.attach_sender(self.send)

    async def send(self, frame, node):
        self.nodes.append(node)

    async def first_write_to(self, node):
        for _ in range(1000):
            if node in self.nodes:
                return
            await asyncio.sleep(0.005)
        raise AssertionError(f"nothing was written to node {node}")


async def test_a_light_whose_model_is_gone_is_never_sent_godox_bytes(tmp_path, demo_models):
    """A Zhiyun model file that was deleted leaves an id like this behind (not a real model id, so no
    Zhiyun driver in a later merge ever owns it). The light sits on the active mesh network, so under the
    old fallback it was commanded through the Godox pump."""
    hub = await _studio(tmp_path, orphan_model="GONE-MODEL")
    try:
        wire = _Wire(hub)
        orphan, key = _light(hub, "Orphan"), _light(hub, "Key light")
        hub.set_state(orphan, LightState(power=True, brightness=40), "test")
        hub.set_state(key, LightState(power=True, brightness=40), "test")  # queued after it: when this is out, the orphan's would be too
        await wire.first_write_to(key.node)
        assert orphan.node not in wire.nodes
        assert orphan.reachable is False
    finally:
        await hub.stop()


async def test_a_light_given_another_brands_model_is_let_go_by_the_godox_pump(tmp_path, demo_models):
    hub = await _studio(tmp_path)
    try:
        fill, key = _light(hub, "Fill"), _light(hub, "Key light")
        hub.godox.attach_sender(None)  # the mesh link is down: writes queue up
        hub.set_state(fill, LightState(power=True, brightness=40), "test")
        hub.set_model(fill.id, "ZY-DEMO")
        wire = _Wire(hub)  # the link comes back
        hub.set_state(key, LightState(power=True, brightness=40), "test")
        await wire.first_write_to(key.node)
        assert fill.node not in wire.nodes
        for _ in range(200):  # and the new driver opened its own link, as it does at start-up
            if fill.reachable:
                break
            await asyncio.sleep(0.005)
        assert fill.reachable is True
    finally:
        await hub.stop()


async def test_forgetting_a_light_clears_what_its_own_driver_kept(tmp_path, demo_models):
    hub = await _studio(tmp_path)
    try:
        key, zhiyun = _light(hub, "Key light"), _light(hub, "Zhiyun panel")
        stand_in = hub.registry.get("demo")
        hub.godox.mark_heard(key.id)
        assert key.reachable is True and zhiyun.id in stand_in.applied
        key_light = key.light
        await hub.forget(key.id)
        await hub.forget(zhiyun.id)
        assert hub.godox.status(key_light)["reachable"] is None  # a light paired again under this id starts unheard
        assert zhiyun.id not in stand_in.applied
    finally:
        await hub.stop()


class _Recorder(Driver):
    """A brand that writes what it is asked to into a shared log, so the order of calls can be read back."""

    id = "rec"

    def __init__(self, log, *, hang_on_stop=False):
        super().__init__()
        self.log, self.hang_on_stop = log, hang_on_stop

    def match(self, advert):
        return None

    async def connect(self, light):
        self.log.append("rec.connect-start")
        await asyncio.sleep(0.05)
        self.log.append("rec.connect-done")

    def apply(self, light, state):
        self.log.append("rec.apply")

    async def identify(self, light):
        return None

    def status(self, light):
        return {"reachable": True, "held": False}

    async def stop(self):
        if self.hang_on_stop:
            await asyncio.Event().wait()  # never returns
        self.log.append("rec.stopped")


REC_MODEL = {"name": "Recorder", "min_kelvin": 2700, "max_kelvin": 6500, "modes": ["cct"], "driver": "rec",
             "brand": "Rec", "match": {}, "driver_data": {}, "demo": True}


async def test_a_driver_that_fails_to_let_go_does_not_stop_a_forget_or_a_model_change(tmp_path, demo_models, monkeypatch):
    hub = await _studio(tmp_path)
    try:
        async def broken(light_id):
            raise KeyError(light_id)

        monkeypatch.setattr(hub.registry.get("demo"), "forget_light", broken)
        wire = _Wire(hub)
        zhiyun, yongnuo = _light(hub, "Zhiyun panel"), _light(hub, "Yongnuo wand")
        hub.set_model(zhiyun.id, "008F")  # to a Godox model; the demo driver fails to let go
        assert hub.library.get(zhiyun.id).radio_id == "008F"
        await wire.first_write_to(zhiyun.node)  # and the Godox driver still took the light over
        await hub.forget(yongnuo.id)  # the same failure must not leave the forget half done
        assert yongnuo.id not in hub.fixtures
        assert all(light.id != yongnuo.id for light in hub.library.lights)
    finally:
        await hub.stop()


async def test_the_old_driver_lets_go_before_the_new_one_connects_and_the_light_is_written_once(tmp_path, demo_models):
    configure_models([], {**demo.DEMO_MODELS, "REC-1": REC_MODEL})
    hub = await _studio(tmp_path)
    log: list[str] = []
    try:
        hub.registry.drivers["rec"] = _Recorder(log)

        async def slow_release(light_id):
            log.append("demo.release-start")
            await asyncio.sleep(0.05)  # closing a link takes time
            log.append("demo.release-done")

        hub.registry.get("demo").forget_light = slow_release
        zhiyun, tasks_before = _light(hub, "Zhiyun panel"), len(hub._tasks)
        hub.set_model(zhiyun.id, "REC-1")
        for _ in range(400):
            if "rec.apply" in log:
                break
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.1)  # time for any second write to show itself
        assert log == ["demo.release-start", "demo.release-done", "rec.connect-start", "rec.connect-done", "rec.apply"]
        assert len(hub._tasks) == tasks_before  # the hand-over task is not kept after it ends
    finally:
        hub.registry.drivers.pop("rec", None)
        await hub.stop()


async def test_a_driver_whose_stop_never_returns_does_not_hold_up_the_hub(tmp_path, demo_models, monkeypatch):
    monkeypatch.setattr(hub_module, "LINK_STOP_SECONDS", 0.2)
    hub = await _studio(tmp_path)
    log: list[str] = []
    hub.registry.drivers = {"hang": _Recorder(log, hang_on_stop=True), "rec": _Recorder(log), **hub.registry.drivers}
    await asyncio.wait_for(hub.stop(), 10)
    assert log == ["rec.stopped"]  # the one after the hung driver was still stopped


async def test_a_driver_that_never_lets_go_does_not_hang_a_forget(tmp_path, demo_models, monkeypatch):
    monkeypatch.setattr(hub_module, "LINK_STOP_SECONDS", 0.2)
    hub = await _studio(tmp_path)
    try:
        async def never(light_id):
            await asyncio.Event().wait()

        hub.registry.get("demo").forget_light = never
        yongnuo = _light(hub, "Yongnuo wand")
        await asyncio.wait_for(hub.forget(yongnuo.id), 5)
        assert all(light.id != yongnuo.id for light in hub.library.lights)
    finally:
        await hub.stop()


async def test_a_cancelled_forget_request_still_finishes_the_forget(tmp_path, demo_models):
    hub = await _studio(tmp_path)
    try:
        async def slow(light_id):
            await asyncio.sleep(0.2)

        hub.registry.get("demo").forget_light = slow
        yongnuo = _light(hub, "Yongnuo wand")
        request = asyncio.create_task(hub.forget(yongnuo.id))
        await asyncio.sleep(0.05)  # the driver is letting go
        request.cancel()  # the browser went away
        await asyncio.gather(request, return_exceptions=True)
        for _ in range(300):
            if all(light.id != yongnuo.id for light in hub.library.lights):
                break
            await asyncio.sleep(0.01)
        assert all(light.id != yongnuo.id for light in hub.library.lights)
    finally:
        await hub.stop()


async def test_a_model_change_connects_nothing_before_start_or_after_stop(tmp_path, demo_models):
    configure_models([], {**demo.DEMO_MODELS, "REC-1": REC_MODEL})
    library = LightLibrary(tmp_path)
    demo.seed(library)
    hub = Hub(Store(tmp_path), library, demo=True, scanner=demo.DemoScanner())
    log: list[str] = []
    hub.registry.drivers["rec"] = _Recorder(log)
    zhiyun, yongnuo = _light(hub, "Zhiyun panel"), _light(hub, "Yongnuo wand")
    hub.set_model(zhiyun.id, "REC-1")  # not started yet
    await asyncio.sleep(0.2)
    assert log == []
    await hub.start()
    await hub.stop()
    log.clear()
    hub.set_model(yongnuo.id, "REC-1")  # already stopped
    await asyncio.sleep(0.2)
    assert log == []
