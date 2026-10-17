"""Saved lights, their mesh networks, and recognising lights nearby. No hardware."""

from __future__ import annotations

import dataclasses
import json

import pytest
from godox_mesh_bt.crypto import k3
from godox_mesh_bt.state import MeshState

from gaffer.discovery import MESH_PROV, MESH_PROXY, radio_id_from_manufacturer, read_advert
from gaffer.lights import LightLibrary
from gaffer.link import ROTATION_BASE

NET = "11" * 16
APP = "22" * 16


def _keys(**over):
    base = {"network_key": NET, "app_key": APP, "provisioner_address": 1, "node_address": 2,
            "sequence_number": 5000, "iv_index": 0, "device_key": "33" * 16}
    return MeshState(**{**base, **over})


@pytest.fixture
def library(tmp_path):
    return LightLibrary(tmp_path)


# -- the library ------------------------------------------------------------------


def test_a_new_library_is_empty(library):
    assert library.lights == ()
    assert library.active is None


def test_importing_keys_saves_the_light_and_makes_it_active(library, tmp_path):
    light = library.import_keys(_keys(), address="a4:c1:38:00:00:01", name="Key light", radio_id="008F")
    assert light.address == "A4:C1:38:00:00:01" and light.node_address == 2
    assert library.active == light
    reopened = LightLibrary(tmp_path)
    assert reopened.active == light
    assert reopened.network_state(light.network).network_key == NET


def test_imported_keys_get_their_own_source_address(library):
    """The tool that made the keys keeps its counter; ours must never collide with it."""
    light = library.import_keys(_keys(provisioner_address=1, sequence_number=9_000), address="AA:00", name="A")
    state = library.network_state(light.network)
    assert state.provisioner_address == ROTATION_BASE
    assert state.sequence_number == 0
    other = library.import_keys(
        _keys(network_key="44" * 16, provisioner_address=ROTATION_BASE), address="BB:00", name="B"
    )
    assert library.network_state(other.network).provisioner_address == ROTATION_BASE + 1


def test_a_second_light_on_the_same_network_shares_it(library):
    first = library.import_keys(_keys(), address="AA:00", name="A")
    second = library.import_keys(_keys(node_address=4, device_key="55" * 16), address="BB:00", name="B")
    assert first.network == second.network
    assert len(list(library.root.glob("networks/*.json"))) == 1


def test_reimporting_the_same_light_updates_it_rather_than_duplicating(library):
    library.import_keys(_keys(), address="AA:00", name="A")
    library.import_keys(_keys(), address="AA:00", name="A again")
    assert len(library.lights) == 1 and library.lights[0].name == "A again"


def test_node_addresses_skip_every_element_already_taken(library):
    library.import_keys(_keys(node_address=2), address="AA:00", name="A")
    network = library.active.network
    assert library.next_node_address(network) == 4
    library.save_light(dataclasses.replace(library.active, id="x", address="CC:00", node_address=4, num_elements=3))
    assert library.next_node_address(network) == 7


def test_a_fresh_network_has_random_keys(library):
    a = library.network_state(library.create_network())
    b = library.network_state(library.create_network())
    assert a.network_key != b.network_key and len(a.app_key) == 32


def test_forgetting_the_active_light_moves_to_the_next(library):
    a = library.import_keys(_keys(), address="AA:00", name="A")
    b = library.import_keys(_keys(node_address=4), address="BB:00", name="B")
    library.set_active(a.id)
    assert library.forget(a.id) == b
    assert library.active == b
    assert library.forget(b.id) is None and library.active is None


def test_rename_and_model_override(library):
    light = library.import_keys(_keys(), address="AA:00", name="A", radio_id="008F")
    library.rename(light.id, "  Fill  ")
    library.set_model(light.id, "003A", source="manual")
    saved = library.get(light.id)
    assert (saved.name, saved.radio_id, saved.model_source) == ("Fill", "003A", "manual")
    with pytest.raises(ValueError):
        library.rename(light.id, "   ")


def test_a_corrupt_library_file_is_set_aside_not_lost(tmp_path):
    (tmp_path / "lights.json").write_text("{not json", encoding="utf-8")
    library = LightLibrary(tmp_path)
    assert library.lights == ()
    assert list(tmp_path.glob("lights.json.corrupt-*"))


def test_keys_never_appear_in_the_public_view(library):
    light = library.import_keys(_keys(), address="AA:00", name="A", radio_id="008F")
    text = json.dumps(library.public())
    assert NET not in text and APP not in text and "33" * 16 not in text
    assert library.public()["lights"][0]["id"] == light.id


# -- recognising lights in the air -------------------------------------------------------


def _godox_manufacturer(radio_id: str) -> dict[int, bytes]:
    """Manufacturer data as bleak reports it: company id as the key, radioId at blob[6:8]."""
    model = bytes.fromhex(radio_id)
    low, high = model[1], model[0]
    return {0x5F2C: bytes([0, 0, 0, 0, low, high, 0, 0])}


def test_the_model_id_is_read_from_manufacturer_data():
    assert radio_id_from_manufacturer(_godox_manufacturer("008F")) == "008F"
    assert radio_id_from_manufacturer({0x1234: b"\x00"}) is None
    assert radio_id_from_manufacturer({}) is None


def test_an_unpaired_godox_light_is_recognised():
    seen = read_advert("AA:BB", "GD_LED", -60, [MESH_PROV], {}, _godox_manufacturer("003A"))
    assert seen is not None
    assert (seen.state, seen.radio_id, seen.network_id) == ("unpaired", "003A", None)


def test_a_paired_light_carries_its_network_id():
    network_id = k3(bytes.fromhex(NET))
    seen = read_advert("AA:BB", None, -70, [MESH_PROXY], {MESH_PROXY: b"\x00" + network_id}, {})
    assert seen is not None and seen.state == "mesh" and seen.network_id == network_id.hex()


def test_unrelated_devices_are_ignored():
    assert read_advert("AA:BB", "Headphones", -40, [], {}, {}) is None
    assert read_advert("AA:BB", "Other mesh bulb", -40, [MESH_PROV], {}, {}) is None


def test_nearby_lights_are_described_against_the_library(library):
    light = library.import_keys(_keys(), address="AA:00", name="Key", radio_id="008F")
    ours = read_advert("CC:00", None, -50, [MESH_PROXY], {MESH_PROXY: b"\x00" + k3(bytes.fromhex(NET))}, {})
    saved = read_advert("AA:00", None, -50, [MESH_PROXY], {}, _godox_manufacturer("008F"))
    fresh = read_advert("DD:00", "GD_LED", -50, [MESH_PROV], {}, _godox_manufacturer("003A"))
    elsewhere = read_advert("EE:00", "GD_LED", -50, [MESH_PROXY], {MESH_PROXY: b"\x00" + bytes(8)}, {})
    described = {n.address: library.describe(n) for n in (ours, saved, fresh, elsewhere)}
    assert described["AA:00"]["relation"] == "saved" and described["AA:00"]["light_id"] == light.id
    assert described["CC:00"]["relation"] == "your-network"
    assert described["DD:00"]["relation"] == "unpaired" and described["DD:00"]["model"] == "SL60IIBi"
    assert described["EE:00"]["relation"] == "elsewhere"
