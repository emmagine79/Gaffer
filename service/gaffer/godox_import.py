"""Read the Godox app's own mesh export, so lights it already paired keep working here.

The export is the Bluetooth Mesh "CDB" JSON document the Godox app keeps in its
local ``GodoxLight.db`` (table ``Project``, column ``meshJson``). It holds the
network key, the application key and every node, so no light needs pairing again.

Ported from ``custom_components/godox_ble_mesh/meshimport.py`` in
SegulaLabs/ha-godox-ble-mesh (MIT, commit 5c90e25; licence in
THIRD-PARTY/ha-godox-ble-mesh/). Changes here: node device keys, MAC addresses
and element counts are read too; the errors are plain sentences; a whole
``GodoxLight.db`` is read from memory.
"""

from __future__ import annotations

import base64
import binascii
import contextlib
import json
import re
import sqlite3
from dataclasses import dataclass
from typing import Any

from godox_mesh_bt.state import MeshState

# Bluetooth SIG company id Godox registers its lights under. The phone app's own
# provisioner entry in the export has no "cid" at all, and another vendor's mesh
# device on the same network carries a different one, so this, not the node's
# name (whatever the installer typed in the app), separates a Godox light from noise.
GODOX_COMPANY_ID = "0211"

#: The most one WebSocket message can carry: uvicorn's default ``ws_max_size`` (16 MiB, uvicorn 0.54
#: ``Config``). A bigger message makes uvicorn close the socket (code 1009) before any handler runs, so
#: the page cannot be told why. The web page checks its file against this before sending
#: (``web/src/add/GodoxImport.tsx``); a file travels as base64, 4 characters for every 3 bytes, so the
#: largest one that can arrive is a little under 12 MiB. These checks only guard the text that did arrive.
MAX_BYTES = 16 * 1024 * 1024

#: Bluetooth Mesh unicast addresses run 0x0001 to 0x7FFF (Mesh Protocol spec, 3.4.2.2).
_UNICAST = range(0x0001, 0x8000)
_ELEMENTS_DEFAULT = 2  # what the library assumes when a node does not list its elements
_HEX32 = re.compile(r"^[0-9a-fA-F]{32}$")
_MAC = re.compile(r"^[0-9a-fA-F]{12}$")


class ImportProblem(ValueError):
    """The file or text cannot be used. The message is plain words with no path in it."""


@dataclass(frozen=True)
class FoundNode:
    name: str
    address: int  # the mesh unicast address
    device_key: str
    bluetooth_address: str
    num_elements: int


@dataclass(frozen=True)
class MeshImport:
    network_key: str
    app_key: str
    iv_index: int
    nodes: list[FoundNode]


def _key(value: Any) -> str | None:
    if isinstance(value, str) and _HEX32.match(value.strip()):
        return value.strip().lower()
    return None


def _is_godox(cid: Any) -> bool:
    """Whether a node's company id is Godox's, written as ``"0211"``, ``"0x0211"`` or the number 529."""
    if isinstance(cid, bool):
        return False
    if isinstance(cid, int):
        return cid == int(GODOX_COMPANY_ID, 16)
    if not isinstance(cid, str):
        return False
    text = cid.strip().lower().removeprefix("0x")
    try:
        return int(text, 16) == int(GODOX_COMPANY_ID, 16)
    except ValueError:
        return False


def parse_mesh_export(text: str) -> MeshImport:
    if len(text) > MAX_BYTES:
        raise ImportProblem("That file is too large to be a Godox export.")
    try:
        data = json.loads(text)
    except ValueError as err:
        raise ImportProblem("That text is not a Godox mesh export (it is not JSON).") from err
    if not isinstance(data, dict):
        raise ImportProblem("That text is not a Godox mesh export (expected a JSON object).")

    try:
        network_key = _key(data["netKeys"][0]["key"])
        app_key = _key(data["appKeys"][0]["key"])
    except (KeyError, IndexError, TypeError):
        network_key = app_key = None
    if network_key is None or app_key is None:
        raise ImportProblem("That is not a Godox mesh export: it has no network key and app key.")

    iv_index = data.get("ivIndex")
    if not isinstance(iv_index, int) or isinstance(iv_index, bool) or not 0 <= iv_index < 2**32:
        iv_index = 0

    nodes: list[FoundNode] = []
    seen: set[int] = set()
    for node in data.get("nodes") or []:
        if not isinstance(node, dict) or not _is_godox(node.get("cid")):
            continue  # the app's own provisioner entry, or some other vendor's node
        try:
            address = int(str(node["unicastAddress"]), 16)
        except (KeyError, ValueError):
            continue
        if address not in _UNICAST or address in seen:
            continue
        seen.add(address)
        elements = node.get("elements")
        count = len(elements) if isinstance(elements, list) and 1 <= len(elements) <= 32 else _ELEMENTS_DEFAULT
        mac = str(node.get("macAddress") or "").replace(":", "").replace("-", "")
        nodes.append(FoundNode(
            name=str(node.get("name") or "").strip() or f"Godox light 0x{address:04X}",
            address=address,
            device_key=_key(node.get("deviceKey")) or "",
            bluetooth_address=":".join(mac[i:i + 2] for i in range(0, 12, 2)).upper() if _MAC.match(mac) else "",
            num_elements=count,
        ))
    if not nodes:
        raise ImportProblem("No Godox lights found in that export. Check it is the project your lights are in.")
    return MeshImport(network_key=network_key, app_key=app_key, iv_index=iv_index, nodes=nodes)


def mesh_json_from_db(data: bytes) -> str:
    """The ``meshJson`` of the project with the most Godox lights in a ``GodoxLight.db``.

    The file is read from memory and read-only, so no path is ever involved.
    """
    if len(data) > MAX_BYTES:
        raise ImportProblem("That file is too large to be a Godox database.")
    foreign = ImportProblem("That file is not the Godox app's GodoxLight.db.")
    try:
        with contextlib.closing(sqlite3.connect(":memory:")) as db:  # ``with db`` would not close it
            db.deserialize(data)
            db.execute("PRAGMA query_only = ON")
            rows = db.execute("SELECT meshJson FROM Project ORDER BY rowid").fetchall()
    except sqlite3.Error as err:
        raise foreign from err
    best: tuple[int, str] | None = None
    problem: ImportProblem | None = None
    for (value,) in rows:
        if isinstance(value, bytes):
            value = value.decode("utf-8", "replace")
        if not isinstance(value, str):
            continue
        try:
            found = parse_mesh_export(value)
        except ImportProblem as err:
            problem = problem or err
            continue
        if best is None or len(found.nodes) > best[0]:
            best = (len(found.nodes), value)
    if best is None:
        raise problem or ImportProblem("That GodoxLight.db has no project with a mesh export in it.")
    return best[1]


def mesh_import_from_message(message: dict[str, Any]) -> MeshImport:
    """What a ``lights.import`` message carries: pasted ``meshJson``, or a base64 ``db`` file."""
    if isinstance(message.get("meshJson"), str):
        return parse_mesh_export(message["meshJson"])
    db = message.get("db")
    if not isinstance(db, str):
        raise ImportProblem("Paste the meshJson text or choose the GodoxLight.db file.")
    if len(db) > MAX_BYTES:
        raise ImportProblem("That file is too large to be a Godox database.")
    try:
        raw = base64.b64decode(db, validate=True)
    except (binascii.Error, ValueError) as err:
        raise ImportProblem("That file did not arrive intact. Choose it again.") from err
    return parse_mesh_export(mesh_json_from_db(raw))


def light_plans(found: MeshImport) -> list[tuple[str, str, MeshState]]:
    """``(name, Bluetooth address, keys)`` for each Godox light, ready for ``LightLibrary.import_keys``."""
    plans = []
    for node in found.nodes:
        # The export may not say a light's Bluetooth address. A stand-in keeps each light distinct;
        # the link finds lights by network id, not by this address.
        address = node.bluetooth_address or f"GODOX-NODE-{node.address:04X}"
        state = MeshState(
            network_key=found.network_key, app_key=found.app_key, provisioner_address=1,
            node_address=node.address, sequence_number=0, iv_index=found.iv_index,
            device_key=node.device_key, num_elements=node.num_elements,
        )
        plans.append((node.name, address, state))
    return plans
