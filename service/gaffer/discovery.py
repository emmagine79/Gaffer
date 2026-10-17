"""Finding Godox lights in the air, and telling what each one is.

Two facts come from an advertisement alone, without connecting:

* **The model.** Godox puts the light's ``radioId`` in its manufacturer data,
  and its own app reads it from there; that one id picks the light's row in
  the model table. The vendor app reads bytes 7 and 6 of the blob *including*
  the two-byte company id (which these lights fill with part of their own
  address), so the id is read at the same offsets after putting it back.
* **Whose mesh it is on.** A factory-fresh light advertises the Mesh
  Provisioning Service; a paired one advertises the Mesh Proxy Service with
  ``k3(network key)``, its network's public id. Matching that against our own
  keys says whether a light is ours without knowing its address in advance.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

MESH_PROV = "00001827-0000-1000-8000-00805f9b34fb"
MESH_PROXY = "00001828-0000-1000-8000-00805f9b34fb"
_NETWORK_ID_TYPE = 0x00
_GODOX_NAME_PREFIXES = ("gd_", "godox", "ul60", "ul150", "sl", "ml", "lp", "tl")


@dataclass(frozen=True, slots=True)
class Nearby:
    address: str
    name: str | None
    rssi: int | None
    #: ``"unpaired"`` (factory fresh, ready to pair) or ``"mesh"`` (on some network).
    state: str
    radio_id: str | None = None
    #: Hex network id from a proxy advertisement, when it carries one.
    network_id: str | None = None
    seen_at: float = 0.0


def radio_id_from_manufacturer(manufacturer_data: dict[int, bytes] | None) -> str | None:
    """The Godox model id in an advertisement's manufacturer data, if any."""
    for company_id, payload in (manufacturer_data or {}).items():
        blob = int(company_id).to_bytes(2, "little") + bytes(payload)
        if len(blob) <= 9:  # the vendor app requires this before trusting the offsets
            continue
        radio_id = f"{blob[7]:02X}{blob[6]:02X}"
        if radio_id != "0000":
            return radio_id
    return None


def _godox_name(name: str | None) -> bool:
    if not name:
        return False
    normalized = name.lower().replace(" ", "").replace("-", "")
    return normalized.startswith(_GODOX_NAME_PREFIXES) or "godox" in normalized


def read_advert(
    address: str,
    name: str | None,
    rssi: int | None,
    service_uuids: Iterable[str],
    service_data: dict[str, bytes],
    manufacturer_data: dict[int, bytes],
) -> Nearby | None:
    """What one advertisement says about a light, or ``None`` if it is not a Godox mesh light."""
    uuids = {u.lower() for u in service_uuids} | {u.lower() for u in service_data}
    radio_id = radio_id_from_manufacturer(manufacturer_data)
    proxy = service_data.get(MESH_PROXY) or b""
    network_id = proxy[1:9].hex() if len(proxy) >= 9 and proxy[0] == _NETWORK_ID_TYPE else None
    if MESH_PROV in uuids:
        state = "unpaired"
    elif MESH_PROXY in uuids:
        state = "mesh"
    else:
        return None
    if radio_id is None and network_id is None and not _godox_name(name):
        return None  # some other brand's mesh device
    return Nearby(address.upper(), name, rssi, state, radio_id, network_id, time.time())


class Scanner:
    """One-shot scans that keep the platform's device objects for connecting later.

    On Windows a light is far more reliably connected through the object a scan
    returned than through a bare address, so pairing reuses what the scan saw.
    """

    def __init__(self) -> None:
        self.devices: dict[str, Any] = {}
        self.busy = False

    async def scan(self, seconds: float, on_found: Callable[[Nearby], None] | None = None,
                   on_other: Callable[[Any, Any], None] | None = None) -> list[Nearby]:
        """Listen for ``seconds``. ``on_found`` hears each Godox light; ``on_other(device, advert)`` hears every
        other advertisement, so the hub can ask the other brands' drivers whether it is theirs."""
        from bleak import BleakScanner

        found: dict[str, Nearby] = {}

        def callback(device: Any, adv: Any) -> None:
            seen = read_advert(
                device.address, adv.local_name or device.name, adv.rssi, adv.service_uuids or (),
                {k.lower(): bytes(v) for k, v in (adv.service_data or {}).items()},
                {int(k): bytes(v) for k, v in (adv.manufacturer_data or {}).items()},
            )
            if seen is None:
                if on_other is not None:
                    try:
                        on_other(device, adv)
                    except Exception:  # one odd advertisement never ends the scan
                        logger.warning("could not read an advertisement from %s", device.address, exc_info=True)
                return
            self.devices[seen.address] = device
            previous = found.get(seen.address)
            # Proxy and provisioning adverts alternate; keep whichever named the model.
            if previous is not None and seen.radio_id is None:
                seen = Nearby(seen.address, seen.name or previous.name, seen.rssi, seen.state,
                              previous.radio_id, seen.network_id or previous.network_id, seen.seen_at)
            changed = previous != seen
            found[seen.address] = seen
            if changed and on_found is not None:
                on_found(seen)

        self.busy = True
        try:
            async with BleakScanner(detection_callback=callback):
                await asyncio.sleep(seconds)
        finally:
            self.busy = False
        return sorted(found.values(), key=lambda n: -(n.rssi or -999))
