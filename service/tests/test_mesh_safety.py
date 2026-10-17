"""Regressions from review of the multi-light code: addresses, network moves, groups, one studio per folder."""

from __future__ import annotations

import asyncio

import pytest
from godox_mesh_bt.state import MeshState

from gaffer import demo
from gaffer.catalog import model_caps
from gaffer.demo import DemoScanner, seed
from gaffer.discovery import Nearby
from gaffer.hub import Client, Hub
from gaffer.lights import LightLibrary
from gaffer.paths import AlreadyRunning, hold_data_folder
from gaffer.pump import CommandPump
from gaffer.state import Cct, LightState
from gaffer.store import Store

KEYS = {"network_key": "ab" * 16, "app_key": "cd" * 16, "provisioner_address": 1, "node_address": 2,
        "sequence_number": 10, "iv_index": 0, "device_key": "ef" * 16}


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(demo, "PACE", 0.02)


# -- addresses ---------------------------------------------------------------------------------


def test_a_forgotten_lights_address_is_never_handed_out_again(tmp_path):
    """It keeps its keys until reset; a new light on its address would answer for both."""
    library = LightLibrary(tmp_path)
    first = library.import_keys(MeshState(**KEYS), address="AA:00:00:00:00:01", name="A")
    library.import_keys(MeshState(**{**KEYS, "node_address": 4}), address="AA:00:00:00:00:02", name="B")
    library.forget(first.id)
    assert library.next_node_address(first.network) == 6
    assert LightLibrary(tmp_path).next_node_address(first.network) == 6  # and it survives a restart


def test_keys_for_an_address_another_light_holds_are_refused(tmp_path):
    library = LightLibrary(tmp_path)
    library.import_keys(MeshState(**KEYS), address="AA:00:00:00:00:01", name="A")
    with pytest.raises(ValueError, match="already uses node"):
        library.import_keys(MeshState(**KEYS), address="AA:00:00:00:00:02", name="B")


def test_reimporting_keeps_the_name_and_place(tmp_path):
    import dataclasses

    library = LightLibrary(tmp_path)
    light = library.import_keys(MeshState(**KEYS), address="AA:00:00:00:00:01", name="Key")
    library.save_light(dataclasses.replace(light, x=0.2, y=0.7))
    again = library.import_keys(MeshState(**KEYS), address="AA:00:00:00:00:01", name="")
    assert (again.id, again.name, again.x, again.y) == (light.id, "Key", 0.2, 0.7)


def test_forgetting_prefers_a_light_on_the_same_network(tmp_path):
    library = LightLibrary(tmp_path)
    other = library.import_keys(MeshState(**{**KEYS, "network_key": "11" * 16}), address="BB:00:00:00:00:01", name="B1")
    a1 = library.import_keys(MeshState(**KEYS), address="AA:00:00:00:00:01", name="A1")
    a2 = library.import_keys(MeshState(**{**KEYS, "node_address": 4}), address="AA:00:00:00:00:02", name="A2")
    library.set_active(a1.id)
    assert library.forget(a1.id) == a2 and other.network != a2.network


def test_a_saved_light_that_was_reset_shows_as_ready_to_pair(tmp_path):
    library = LightLibrary(tmp_path)
    light = library.import_keys(MeshState(**KEYS), address="AA:00:00:00:00:01", name="Key", radio_id="008F")
    seen = library.describe(Nearby("AA:00:00:00:00:01", "GD_LED", -50, "unpaired", "008F"))
    assert seen["relation"] == "unpaired" and seen["light_id"] == light.id


# -- moving between networks -------------------------------------------------------------------


async def test_writes_queued_for_one_network_never_reach_the_next():
    pump = CommandPump(model_caps("008F"), max_rate=1000, sleep=lambda _s: asyncio.sleep(0))
    pump.submit(LightState(cct=Cct(kelvin=3200)), node=2)
    job = pump.submit_aux(lambda: asyncio.sleep(0))
    pump.reset()
    assert not pump._desired
    with pytest.raises(ConnectionResetError):
        await job


async def _hub(tmp_path) -> Hub:
    library = LightLibrary(tmp_path)
    seed(library)
    hub = Hub(Store(tmp_path), library, demo=True, scanner=DemoScanner())
    await hub.start()
    for _ in range(200):
        if hub.controller is not None:
            break
        await asyncio.sleep(0.01)
    return hub


async def test_moving_the_link_drops_whatever_was_queued(tmp_path):
    hub = await _hub(tmp_path)
    try:
        hub.godox.pump.attach(None)  # as if the link had dropped
        key = next(f for f in hub.fixtures.values() if f.light.name == "Key light")
        hub.set_state(key, key.state.model_copy(update={"brightness": 3.0}), "app")
        assert key.node in hub.godox.pump._desired
        await hub._relink(hub.network)
        assert key.node not in hub.godox.pump._desired
    finally:
        await hub.stop()


async def test_forgetting_a_light_keeps_the_link_on_its_network(tmp_path):
    hub = await _hub(tmp_path)
    try:
        network = hub.network
        first = next(iter(hub.fixtures))
        await hub.forget(first)
        assert hub.network == network and hub.fixtures
    finally:
        await hub.stop()


# -- groups ------------------------------------------------------------------------------------


async def test_a_new_group_follows_the_light_being_worked_on(tmp_path):
    hub = await _hub(tmp_path)
    try:
        ids = {f.light.name: f.id for f in hub.fixtures.values()}
        key, fill = hub.fixtures[ids["Key light"]], hub.fixtures[ids["Fill"]]
        hub.set_state(key, key.state.model_copy(update={"brightness": 15.0}), "app")
        hub.set_state(fill, fill.state.model_copy(update={"brightness": 85.0}), "app")
        group = hub.save_group({"name": "Pair", "members": [ids["Key light"], ids["Fill"]], "props": ["brightness"]},
                               leader=ids["Fill"])
        assert key.state.brightness == 85.0  # the fill, not the first member, led
        hub.set_state(key, key.state.model_copy(update={"brightness": 40.0}), "app", mirror=False)
        hub.save_group({**group, "name": "Renamed"}, leader=ids["Fill"])
        assert key.state.brightness == 40.0  # renaming moved no light
    finally:
        await hub.stop()


# -- one studio per data folder -------------------------------------------------------------------


def test_a_second_studio_cannot_take_the_same_data_folder(tmp_path):
    held = hold_data_folder(tmp_path)
    try:
        with pytest.raises(AlreadyRunning):
            hold_data_folder(tmp_path)
    finally:
        held.close()  # type: ignore[attr-defined]
    hold_data_folder(tmp_path).close()  # type: ignore[attr-defined]  # free again once released


def test_import_through_the_hub_turns_a_clash_into_a_message(tmp_path):
    async def run():
        hub = await _hub(tmp_path)
        try:
            existing = next(iter(hub.fixtures.values()))
            network_key = hub.library.network_state(existing.light.network).network_key
            keys = {**KEYS, "network_key": network_key, "node_address": existing.node}
            with pytest.raises(Exception, match="already uses node"):
                await hub.import_keys(Client(), keys, "CC:00:00:00:00:01")
        finally:
            await hub.stop()

    asyncio.run(run())
