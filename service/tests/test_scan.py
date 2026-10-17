"""Brand tagging of real-shaped advertisements, and one bad advertisement not stopping the list.

The advertisement payloads for GD_LED, YN150Li and PL109_C75E are the ones Gaffer
recorded from Captain's own lights in its first scan on 18 Oct 2026. The devices
use bleak's own BLEDevice and AdvertisementData classes, the objects a real scan
hands to summarize().
"""

from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from gaffer_service.scan import summarize

MESH_PROXY = "00001828-0000-1000-8000-00805f9b34fb"
MESH_PROV = "00001827-0000-1000-8000-00805f9b34fb"


def advert(name, uuids=(), service_data=None, manufacturer_data=None, rssi=-50):
    return AdvertisementData(
        local_name=name,
        manufacturer_data=manufacturer_data or {},
        service_data=service_data or {},
        service_uuids=list(uuids),
        tx_power=None,
        rssi=rssi,
        platform_data=(),
    )


def seen(entries):
    return {addr: (BLEDevice(addr, adv.local_name, None), adv) for addr, adv in entries.items()}


def test_tags_brand_families_and_skips_a_malformed_advert():
    result = summarize(seen({
        # Captain's Godox Litemons LA150Bi, as recorded.
        "godox": advert("GD_LED", [MESH_PROXY],
                        {MESH_PROXY: bytes.fromhex("00a531416af34b7917")},
                        {40644: bytes.fromhex("0938c1a4220002000000ffff00000000000000")}),
        # Captain's Yongnuo, as recorded: service 0xFEFF, not F000AA60.
        "yongnuo": advert("YN150Li", ["0000feff-0000-1000-8000-00805f9b34fb"], None,
                          {1113: bytes.fromhex("180001000101235f356046")}),
        # Captain's Zhiyun MOLUS G200, as recorded: mesh proxy, no 0xFEE9.
        "zhiyun": advert("PL109_C75E", [MESH_PROXY],
                         {MESH_PROXY: bytes.fromhex("0196392b8a425e383c2958df30229d596a")},
                         {2309: bytes.fromhex("706c313039000809020bf0c7010246")}),
        # The service UUIDs SPEC.md names, with names that match no rule.
        "fee9": advert("light-a", ["0000fee9-0000-1000-8000-00805f9b34fb"]),
        "aa60": advert("light-b", ["f000aa60-0451-4000-b000-000000000000"]),
        "unpaired": advert("GD_LED", [MESH_PROV]),
        "other-mesh": advert("Thermostat", [MESH_PROXY]),
        "phone": advert("Someone's phone"),
        # Manufacturer data keyed by text, not a company number: int() fails on it.
        "broken": advert("Broken", manufacturer_data={"not-a-company-id": b"\x01"}),
    }))

    families = {d["id"]: d["family"] for d in result["devices"]}
    assert families == {
        "godox": "godox_mesh",
        "yongnuo": "yongnuo",
        "zhiyun": "zhiyun",
        "fee9": "zhiyun",
        "aa60": "yongnuo",
        "unpaired": "godox_mesh",
        "other-mesh": "bluetooth_mesh",
        "phone": None,
    }
    godox = next(d for d in result["devices"] if d["id"] == "godox")
    assert godox["godox"] == {"state": "mesh", "radio_id": "0022", "network_id": "a531416af34b7917"}
    assert result["skipped"] == [{"id": "broken", "reason": "malformed advertisement"}]
