"""Reading a Godox mesh light from its advertisement alone.

Taken from Rkcr7/lumen-studio, src/lumen_studio/discovery.py at commit
8175526c51b2a8239e51d94c14099cb39e3e3e64 (MIT licence, copyright Matt Gibson,
Simon Cheng and Ritik (Rkcr7); full text in service/third_party/lumen-studio/LICENSE).
Changed for Gaffer: returns a plain dict instead of lumen-studio's Nearby class,
and drops the timestamp.

Two facts come from an advertisement without connecting:

* The model. Godox puts the light's radioId in its manufacturer data, and its
  own app reads it from there. The vendor app reads bytes 7 and 6 of the blob
  including the two-byte company id, so the id is read at the same offsets
  after putting it back.
* Whose mesh it is on. A factory-fresh light advertises the Mesh Provisioning
  Service; a paired one advertises the Mesh Proxy Service with
  k3(network key), its network's public id.
"""

from __future__ import annotations

from collections.abc import Iterable

MESH_PROV = "00001827-0000-1000-8000-00805f9b34fb"
MESH_PROXY = "00001828-0000-1000-8000-00805f9b34fb"
_NETWORK_ID_TYPE = 0x00
_GODOX_NAME_PREFIXES = ("gd_", "godox", "ul60", "ul150", "sl", "ml", "lp", "tl")


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


def godox_name(name: str | None) -> bool:
    if not name:
        return False
    normalized = name.lower().replace(" ", "").replace("-", "")
    return normalized.startswith(_GODOX_NAME_PREFIXES) or "godox" in normalized


def read_godox_advert(
    name: str | None,
    service_uuids: Iterable[str],
    service_data: dict[str, bytes],
    manufacturer_data: dict[int, bytes],
) -> dict[str, str | None] | None:
    """What one advertisement says about a Godox mesh light, or None if it is not one."""
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
    if radio_id is None and network_id is None and not godox_name(name):
        return None  # some other brand's mesh device
    return {"state": state, "radio_id": radio_id, "network_id": network_id}
