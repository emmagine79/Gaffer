"""The hub's light management, driven directly: networks, pairing, recognition, groups."""

from __future__ import annotations

import asyncio

import pytest
from godox_mesh_bt.state import MeshState

from gaffer import demo
from gaffer.demo import DemoScanner, seed
from gaffer.hub import Client, Hub, HubError, NoLink
from gaffer.lights import LightLibrary
from gaffer.state import Cct, LightState
from gaffer.store import Store

KEYS = {"network_key": "ab" * 16, "app_key": "cd" * 16, "provisioner_address": 1, "node_address": 2,
        "sequence_number": 10, "iv_index": 0, "device_key": "ef" * 16}


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(demo, "PACE", 0.02)


async def _hub(tmp_path, *, seeded=True, pairer=None) -> Hub:
    library = LightLibrary(tmp_path)
    if seeded:
        seed(library)
    hub = Hub(Store(tmp_path), library, demo=True, scanner=DemoScanner(), pairer=pairer)
    await hub.start()
    return hub


async def _connected(hub: Hub) -> None:
    for _ in range(200):
        if hub.controller is not None:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("never connected")


def _id(hub: Hub, name: str) -> str:
    return next(f.id for f in hub.fixtures.values() if f.light.name == name)


async def test_an_empty_studio_waits_for_a_first_light(tmp_path):
    hub = await _hub(tmp_path, seeded=False)
    try:
        assert isinstance(hub.link, NoLink) and hub.default_light_id() is None
        with pytest.raises(HubError, match="no light yet"):
            hub.fixture(None)
    finally:
        await hub.stop()


async def test_importing_keys_adds_the_light_and_connects_to_its_network(tmp_path):
    hub = await _hub(tmp_path, seeded=False)
    try:
        client = Client()
        light = await hub.import_keys(client, KEYS, "aa:bb:cc:dd:ee:ff", "Key", "008F")
        assert client.selected == light.id and hub.network == light.network
        assert hub.fixtures[light.id].caps.name == "ML100R"
        assert not isinstance(hub.link, NoLink)
        with pytest.raises(HubError, match="not usable"):
            await hub.import_keys(client, {"network_key": "zz"}, "AA:00:00:00:00:0A", "Bad")
    finally:
        await hub.stop()


async def test_a_failed_pairing_goes_back_to_the_lights_you_had(tmp_path):
    async def broken(target, **kwargs):
        kwargs["on_step"]("provisioning")
        raise TimeoutError("light stopped answering")

    hub = await _hub(tmp_path, pairer=broken)
    try:
        await _connected(hub)
        before = set(hub.fixtures)
        await hub.scan(1)
        with pytest.raises(HubError, match="pairing failed"):
            await hub.pair(Client(), "DE:MO:00:00:00:10")
        assert hub.pairing["step"] == "failed" and set(hub.fixtures) == before
        await _connected(hub)  # the link came back
    finally:
        await hub.stop()


async def test_selecting_a_light_on_another_network_moves_the_link(tmp_path):
    hub = await _hub(tmp_path)
    try:
        await _connected(hub)
        client = Client()
        other = await hub.import_keys(client, KEYS, "AA:00:00:00:00:0A", "Elsewhere", "003A")
        assert hub.network == other.network
        await hub.select(client, _id(hub, "Key light"))
        assert hub.network == other.network  # looking at a light does not move the link
        await hub.select(client, _id(hub, "Key light"), connect=True)
        assert hub.network == hub.fixtures[_id(hub, "Key light")].light.network
        assert not hub.on_network(hub.fixtures[other.id])
    finally:
        await hub.stop()


async def test_forgetting_the_last_light_leaves_an_empty_studio(tmp_path):
    hub = await _hub(tmp_path, seeded=False)
    try:
        light = await hub.import_keys(Client(), KEYS, "AA:00:00:00:00:0A", "Only")
        await hub.forget(light.id)
        assert hub.fixtures == {} and isinstance(hub.link, NoLink)
        assert LightLibrary(tmp_path).lights == ()
    finally:
        await hub.stop()


async def test_a_light_names_its_own_model_unless_the_user_chose_one(tmp_path):
    hub = await _hub(tmp_path, seeded=False)
    try:
        client = Client()
        light = await hub.import_keys(client, KEYS, "AA:00:00:00:00:0A", "Mystery")
        assert not hub.fixtures[light.id].caps.known
        hub._on_advert("AA:00:00:00:00:0A", "003A")
        assert hub.fixtures[light.id].caps.name == "SL60IIBi"
        hub.set_model(light.id, "00D0")
        hub._on_advert("AA:00:00:00:00:0A", "003A")  # a manual choice is not overridden
        assert hub.fixtures[light.id].caps.name == "SL300Bi"
    finally:
        await hub.stop()


async def test_a_new_model_refits_the_lights_state(tmp_path):
    hub = await _hub(tmp_path)
    try:
        key = hub.fixtures[_id(hub, "Key light")]
        hub.set_state(key, LightState(mode="hsi"), "app")
        hub.set_model(key.id, "003A")  # it turns out to be a bi-colour light
        assert key.state.mode == "cct"
    finally:
        await hub.stop()


async def test_effects_spread_through_a_group_only_when_effects_are_synced(tmp_path):
    hub = await _hub(tmp_path)
    try:
        await _connected(hub)
        key, hair = hub.fixtures[_id(hub, "Key light")], hub.fixtures[_id(hub, "Hair light")]
        hub.save_group({"name": "Pair", "members": [key.id, hair.id], "props": ["colour"]})
        hub.set_state(hair, hair.state.model_copy(update={"mode": "cct", "cct": Cct(kelvin=4000)}), "app")
        key.engine.start_effect("rainbow", {"period": 1})
        await asyncio.sleep(0.2)
        assert hair.state.mode == "cct"  # an animation is not a colour change
        hub.save_group({"id": hub.groups[0]["id"], "name": "Pair", "members": [key.id, hair.id],
                        "props": ["colour", "effects"]})
        await asyncio.sleep(0.2)
        assert hair.state.mode == "hsi" and hair.state_source == "group"
    finally:
        await hub.stop()


async def test_states_survive_a_restart_per_light(tmp_path):
    hub = await _hub(tmp_path)
    fill = _id(hub, "Fill")
    hub.set_state(hub.fixtures[fill], LightState(brightness=37, cct=Cct(kelvin=3100)), "app")
    await hub.stop()
    again = await _hub(tmp_path)
    try:
        assert again.fixtures[fill].state.brightness == 37 and again.fixtures[fill].state.cct.kelvin == 3100
    finally:
        await again.stop()


def test_keys_from_the_command_line_are_saved(tmp_path):
    state = MeshState(**KEYS)
    light = LightLibrary(tmp_path).import_keys(state, address="AA:00:00:00:00:0A", name="CLI", radio_id="008F")
    assert LightLibrary(tmp_path).active == light
