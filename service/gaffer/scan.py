"""Listen for Bluetooth advertisements and say which brand family each device belongs to.

Scan only. This module listens to advertisements through BleakScanner and never
connects to a device or writes to one. Writing to a light needs Captain's
go-ahead (SPEC.md, "Rules for the build").
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .discovery import MESH_PROV, MESH_PROXY, read_advert

log = logging.getLogger("gaffer.scan")

# Brand-family service UUIDs, from SPEC.md ("The outcome" table) and PRIOR-ART.md.
ZHIYUN_SERVICE = "0000fee9-0000-1000-8000-00805f9b34fb"  # ZY Vega, 0xFEE9
YONGNUO_SERVICE = "f000aa60-0451-4000-b000-000000000000"  # TI UART service F000AA60

# Zhiyun local-name prefixes: didim99/HA-Zhiyun-Light (MIT), custom_components/zhiyun_ble/manifest.json
# at commit 7ca51ea, licence in THIRD-PARTY/HA-Zhiyun-Light/LICENSE.
# Needed because a real MOLUS G200 advertises as "PL109_C75E" with the mesh proxy
# service 0x1828 and no 0xFEE9 (Gaffer scan, 18 Oct 2026).
ZHIYUN_NAME_PREFIXES = ("PL0", "PL1", "PLB", "PLG", "PLM", "PLX")

# Scan length in seconds: lumen-studio's default and clamp (service/gaffer/commands.py, lights.scan).
DEFAULT_SCAN_SECONDS = 6.0
MIN_SCAN_SECONDS = 2.0
MAX_SCAN_SECONDS = 20.0

FAMILY_LABELS = {
    "godox_mesh": "Godox mesh",
    "zhiyun": "Zhiyun",
    "yongnuo": "Yongnuo",
    "bluetooth_mesh": "Bluetooth mesh (not Godox)",
}


def yongnuo_name(name: str | None) -> bool:
    """Yongnuo's name rule, from asidjwiaijd/yongnuo-light-control (MIT),
    yn_light_control/lib/light_controller.dart _looksLikeYongnuoDevice at commit 970a2f0,
    licence in THIRD-PARTY/yongnuo-light-control/LICENSE.

    Needed because a real YN150Li advertises service 0xFEFF, not F000AA60 (Gaffer scan, 18 Oct 2026).
    """
    if not name:
        return False
    n = name.lower()
    return "yongnuo" in n or n.startswith("yn") or "p360" in n


def classify(name: str | None, adv: Any) -> dict[str, Any]:
    """One device's entry in the scan list: its name, signal, brand family and why.

    Raises if the advertisement is malformed; summarize() records that device as skipped.
    """
    service_uuids = [str(u).lower() for u in (adv.service_uuids or ())]
    service_data = {str(k).lower(): bytes(v) for k, v in (adv.service_data or {}).items()}
    manufacturer_data = {int(k): bytes(v) for k, v in (adv.manufacturer_data or {}).items()}
    advertised = set(service_uuids) | set(service_data)

    family: str | None = None
    match: str | None = None
    detail: dict[str, Any] = {}
    if ZHIYUN_SERVICE in advertised:
        family, match = "zhiyun", "service 0xFEE9"
    elif name and name.upper().startswith(ZHIYUN_NAME_PREFIXES):
        family, match = "zhiyun", "Zhiyun model name"
    elif YONGNUO_SERVICE in advertised:
        family, match = "yongnuo", "service F000AA60"
    elif yongnuo_name(name):
        family, match = "yongnuo", "Yongnuo name"
    elif MESH_PROV in advertised or MESH_PROXY in advertised:
        # lumen-studio's reader (discovery.read_advert): the model id and mesh network id from the advert alone.
        godox = read_advert("", name, None, service_uuids, service_data, manufacturer_data)
        if godox is not None:
            family, match = "godox_mesh", "mesh service with Godox model id or name"
            detail = {"state": godox.state, "radio_id": godox.radio_id, "network_id": godox.network_id}
        else:
            family, match = "bluetooth_mesh", "mesh service, no Godox model id"

    rssi = adv.rssi
    return {
        "name": name,
        "rssi": int(rssi) if rssi is not None else None,
        "family": family,
        "family_label": FAMILY_LABELS.get(family) if family else None,
        "match": match,
        "services": sorted(advertised),
        "manufacturer_data": {str(k): v.hex() for k, v in sorted(manufacturer_data.items())},
        "service_data": {k: v.hex() for k, v in sorted(service_data.items())},
        **({"godox": detail} if detail else {}),
    }


def summarize(seen: dict[str, tuple[Any, Any]]) -> dict[str, Any]:
    """Turn raw scan results (address -> (BLEDevice, AdvertisementData)) into the API answer.

    One malformed advertisement never stops the list: it is counted as skipped with a reason.
    """
    devices: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for address, pair in seen.items():
        try:
            device, adv = pair
            name = adv.local_name or device.name
            entry = classify(name, adv)
            entry["id"] = str(address)
            devices.append(entry)
        except Exception as err:  # one bad advertisement must not end the scan
            log.warning("skipped advertisement from %s: %r", address, err)
            skipped.append({"id": str(address), "reason": "malformed advertisement"})
    devices.sort(key=lambda d: (d["family"] is None, -(d["rssi"] if d["rssi"] is not None else -999)))
    return {"devices": devices, "skipped": skipped}


def merge_adverts(old: Any, new: Any) -> Any:
    """Combine two AdvertisementData from one device; the newer one wins on conflicts."""
    return new._replace(
        local_name=new.local_name or old.local_name,
        service_uuids=sorted(set(old.service_uuids or ()) | set(new.service_uuids or ())),
        service_data={**(old.service_data or {}), **(new.service_data or {})},
        manufacturer_data={**(old.manufacturer_data or {}), **(new.manufacturer_data or {})},
    )


class Scanner:
    """Runs one scan at a time; a second request waits for the first to finish."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()

    async def scan(self, seconds: float) -> dict[str, Any]:
        from bleak import BleakScanner

        seen: dict[str, tuple[Any, Any]] = {}

        def on_advert(device: Any, adv: Any) -> None:
            # A light can send different adverts in turn (mesh proxy, provisioning,
            # scan response), so keep what all of them said during this scan.
            previous = seen.get(device.address)
            if previous is not None:
                try:
                    adv = merge_adverts(previous[1], adv)
                except Exception:  # a malformed advert is left for summarize() to skip
                    pass
            seen[device.address] = (device, adv)

        async with self._lock:
            async with BleakScanner(detection_callback=on_advert):
                await asyncio.sleep(seconds)
        result = summarize(seen)
        result["seconds"] = seconds
        return result


class DemoScanner:
    """Demo mode's stand-in for Scanner: a fixed set of adverts, no Bluetooth.

    The adverts are made-up lookalikes of the three brands' (invented names; Godox's public model id), run through the
    same summarize() as a real scan, so demo mode shows the real tagging without starting a scan.
    """

    async def scan(self, seconds: float) -> dict[str, Any]:
        from bleak.backends.device import BLEDevice
        from bleak.backends.scanner import AdvertisementData

        def advert(name: str, uuids: list[str], service_data: dict[str, bytes], manufacturer: dict[int, bytes],
                   rssi: int) -> AdvertisementData:
            return AdvertisementData(local_name=name, manufacturer_data=manufacturer, service_data=service_data,
                                     service_uuids=uuids, tx_power=None, rssi=rssi, platform_data=())

        adverts = {
            "DEMO-GODOX": advert("GD_LED", [MESH_PROXY], {MESH_PROXY: bytes.fromhex("0011223344556677aa")},
                                 {40644: bytes.fromhex("0938c1a4220002000000ffff00000000000000")}, -48),
            "DEMO-YONGNUO": advert("YN-DEMO", ["0000feff-0000-1000-8000-00805f9b34fb"], {}, {}, -61),
            "DEMO-ZHIYUN": advert("PL000_DEMO", [MESH_PROXY], {}, {}, -67),
            "DEMO-OTHER": advert("Someone's phone", [], {}, {}, -80),
        }
        result = summarize({k: (BLEDevice(k, v.local_name, None), v) for k, v in adverts.items()})
        result["seconds"] = seconds
        return result
