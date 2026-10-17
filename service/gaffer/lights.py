"""The lights this studio knows, and the mesh networks they sit on.

Two kinds of file, both in the data folder and never in the repository:

``lights.json``
    Every saved light: name, Bluetooth address, model, its unicast address on
    its network, and its device key (needed only to re-bind it, and never sent
    to the browser). Plus which light is active.
``networks/<id>.json``
    One mesh network's keys and sequence counter, in the library's own
    ``mesh_state.json`` format, so it can be read by the ``godox-mesh`` CLI too.

Lights paired here join one shared network, the way the vendor app and Home
Assistant do it. That matters for sequence numbers: a light keeps a replay
record per source address, and a relayed command reaches every light on the
mesh, so all lights on a network must share one counter rather than each
keeping its own.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import secrets
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from godox_mesh_bt.crypto import k3
from godox_mesh_bt.state import MeshState

from .catalog import model_caps
from .discovery import Nearby
from .link import ROTATION_BASE, ROTATION_LAST

logger = logging.getLogger(__name__)

LIGHTS_FILE = "lights.json"
NETWORKS_DIR = "networks"
FIRST_NODE_ADDRESS = 0x0002
DEFAULT_ELEMENTS = 2


@dataclass(frozen=True, slots=True)
class SavedLight:
    id: str
    name: str
    address: str
    radio_id: str
    network: str
    node_address: int
    num_elements: int = DEFAULT_ELEMENTS
    #: Needed to re-bind the light's application key; unrecoverable once lost.
    device_key: str = ""
    #: ``"advert"`` when the model came from the light itself, ``"manual"`` when picked.
    model_source: str = "advert"
    added: float = 0.0
    #: Where the light stands on the mesh screen's floor plan, 0-1 each way.
    x: float | None = None
    y: float | None = None
    #: The radio channel a light is set to, for brands that need one told to them (Yongnuo).
    #: ``None`` for lights that have no such setting. Set when the light is added.
    channel: int | None = None

    def public(self) -> dict[str, Any]:
        """Everything the browser may see: no keys."""
        caps = model_caps(self.radio_id)
        return {
            "id": self.id, "name": self.name, "address": self.address, "radio_id": self.radio_id,
            "model": caps.name, "kind": caps.kind, "known_model": caps.known,
            "model_source": self.model_source, "node_address": self.node_address, "added": self.added,
            "network": self.network, "x": self.x, "y": self.y, "channel": self.channel,
        }


def _write_json(path: Path, data: Any) -> None:
    """Write-then-rename, so a crash mid-write never truncates the file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _fresh_source(taken: set[int]) -> int:
    """A source address no other tool or network here is using."""
    for candidate in range(ROTATION_BASE, ROTATION_LAST + 1):
        if candidate not in taken:
            return candidate
    raise RuntimeError("no free source address left")


class LightLibrary:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._active: str | None = None
        self._lights: dict[str, SavedLight] = {}
        #: Address ranges of forgotten lights, by network. A forgotten light keeps
        #: its keys until it is reset, so its addresses are never handed out again.
        self._retired: dict[str, list[list[int]]] = {}
        self._load()

    # -- persistence ----------------------------------------------------------------

    def _load(self) -> None:
        path = self.root / LIGHTS_FILE
        if not path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            lights = [SavedLight(**item) for item in raw.get("lights", [])]
        except (ValueError, TypeError) as err:
            aside = path.with_name(f"{path.name}.corrupt-{int(time.time())}")
            os.replace(path, aside)
            logger.error("lights file unreadable (%s); moved it to %s and started empty", err, aside.name)
            return
        self._lights = {light.id: light for light in lights}
        retired = raw.get("retired") or {}
        self._retired = {str(k): [[int(a), int(b)] for a, b in v] for k, v in retired.items()} if isinstance(retired, dict) else {}
        active = raw.get("active")
        self._active = active if active in self._lights else None

    def _save(self) -> None:
        _write_json(self.root / LIGHTS_FILE, {
            "active": self._active,
            "lights": [dataclasses.asdict(light) for light in self._lights.values()],
            "retired": self._retired,
        })

    # -- lights -------------------------------------------------------------------------

    @property
    def lights(self) -> tuple[SavedLight, ...]:
        return tuple(self._lights.values())

    @property
    def active(self) -> SavedLight | None:
        return self._lights.get(self._active) if self._active else None

    def get(self, light_id: str) -> SavedLight:
        try:
            return self._lights[light_id]
        except KeyError:
            raise KeyError(f"no saved light {light_id!r}") from None

    def by_address(self, address: str) -> SavedLight | None:
        return next((light for light in self._lights.values() if light.address == address.upper()), None)

    def set_active(self, light_id: str | None) -> None:
        if light_id is not None:
            self.get(light_id)
        self._active = light_id
        self._save()

    def save_light(self, light: SavedLight) -> SavedLight:
        self._lights[light.id] = light
        self._save()
        return light

    def rename(self, light_id: str, name: str) -> SavedLight:
        name = name.strip()
        if not name:
            raise ValueError("a light needs a name")
        return self.save_light(dataclasses.replace(self.get(light_id), name=name[:60]))

    def set_model(self, light_id: str, radio_id: str, *, source: str) -> SavedLight:
        return self.save_light(dataclasses.replace(self.get(light_id), radio_id=radio_id.upper(), model_source=source))

    def forget(self, light_id: str) -> SavedLight | None:
        """Drop a light from the library. Returns the light that is active afterwards."""
        gone = self.get(light_id)
        del self._lights[light_id]
        self._retired.setdefault(gone.network, []).append([gone.node_address, max(1, gone.num_elements)])
        if self._active == light_id:
            # The next light on the same network, so the link need not move.
            same = [light.id for light in self._lights.values() if light.network == gone.network]
            self._active = same[0] if same else next(iter(self._lights), None)
        self._save()
        return self.active

    def public(self) -> dict[str, Any]:
        return {"active": self._active, "lights": [light.public() for light in self._lights.values()]}

    # -- networks --------------------------------------------------------------------------

    def network_path(self, network_id: str) -> Path:
        return self.root / NETWORKS_DIR / f"{network_id}.json"

    def network_state(self, network_id: str) -> MeshState:
        return MeshState.load(self.network_path(network_id))

    def network_ids(self) -> list[str]:
        folder = self.root / NETWORKS_DIR
        return sorted(p.stem for p in folder.glob("*.json")) if folder.exists() else []

    def _network_for_key(self, network_key: str) -> str | None:
        for network_id in self.network_ids():
            if self.network_state(network_id).network_key.lower() == network_key.lower():
                return network_id
        return None

    def _sources_in_use(self) -> set[int]:
        return {self.network_state(n).provisioner_address for n in self.network_ids()}

    def _write_network(self, state: MeshState) -> str:
        network_id = uuid.uuid4().hex[:8]
        _write_json(self.network_path(network_id), state.to_dict())
        return network_id

    def create_network(self) -> str:
        """A new network with random keys, for pairing a first light."""
        return self._write_network(MeshState(
            network_key=secrets.token_hex(16), app_key=secrets.token_hex(16),
            provisioner_address=0x0001, node_address=0, sequence_number=0, iv_index=0,
        ))

    def default_network(self) -> str:
        """The network new lights are paired onto: the active light's, else any, else a new one."""
        if self.active is not None:
            return self.active.network
        existing = self.network_ids()
        return existing[0] if existing else self.create_network()

    def network_ids_by_public_id(self) -> dict[str, str]:
        """Our networks keyed by the id their lights advertise (``k3`` of the key)."""
        return {k3(bytes.fromhex(self.network_state(n).network_key)).hex(): n for n in self.network_ids()}

    def next_node_address(self, network_id: str) -> int:
        """The lowest primary address whose elements are all free, for a new light."""
        taken: set[int] = set()
        for light in self._lights.values():
            if light.network == network_id:
                taken.update(range(light.node_address, light.node_address + max(1, light.num_elements)))
        for start, count in self._retired.get(network_id, ()):
            taken.update(range(start, start + count))
        candidate = FIRST_NODE_ADDRESS
        while any(candidate + offset in taken for offset in range(DEFAULT_ELEMENTS)):
            candidate += 1
        return candidate

    # -- adding lights ------------------------------------------------------------------------

    def import_keys(
        self, state: MeshState, *, address: str, name: str, radio_id: str = "", source: str = "advert",
        keep_name: bool = False,
    ) -> SavedLight:
        """Save a light that was paired elsewhere, from its ``mesh_state.json``.

        A light already saved at this address keeps what was settled in Gaffer: only its keys are
        updated. A name typed in now still renames it, but not with ``keep_name`` (a name that came
        from an export, not from a person). A model picked by hand, or already known, is not replaced
        by a guess; only a model picked by hand now (``source="manual"``) replaces it.

        A network seen for the first time gets a source address of its own, at
        sequence 0: the light keeps a separate replay record per source, so the
        tool that made the keys can carry on using its own counter without
        either one's commands being dropped as replays of the other's.
        """
        network_id = self._network_for_key(state.network_key)
        if network_id is None:
            fresh = dataclasses.replace(
                state, provisioner_address=_fresh_source(self._sources_in_use() | {state.provisioner_address}),
                sequence_number=0, device_key="", node_address=0,
            )
            network_id = self._write_network(fresh)
        existing = self.by_address(address)
        span = range(state.node_address, state.node_address + max(1, state.num_elements))
        for other in self._lights.values():
            if other.network == network_id and other.address != address.upper() and (
                    set(span) & set(range(other.node_address, other.node_address + max(1, other.num_elements)))):
                raise ValueError(f"{other.name} already uses node 0x{state.node_address:04x} on that network; "
                                 "these keys belong to another light")
        if existing and keep_name:
            name = existing.name
        radio, model_source = radio_id.upper(), source
        if existing and existing.radio_id and source != "manual":
            radio, model_source = existing.radio_id, existing.model_source
        elif existing and not radio_id:
            radio, model_source = existing.radio_id, existing.model_source
        light = SavedLight(
            id=existing.id if existing else uuid.uuid4().hex[:10],
            name=name.strip()[:60] or (existing.name if existing else model_caps(radio_id).name),
            address=address.upper(),
            radio_id=radio,
            network=network_id,
            node_address=state.node_address,
            num_elements=state.num_elements,
            device_key=state.device_key,
            model_source=model_source,
            added=existing.added if existing else time.time(),
            x=existing.x if existing else None,
            y=existing.y if existing else None,
            channel=existing.channel if existing else None,
        )
        self.save_light(light)
        self.set_active(light.id)
        return light

    def add_paired(
        self, *, network_id: str, address: str, radio_id: str, node_address: int, num_elements: int,
        device_key: str, name: str = "",
    ) -> SavedLight:
        """Save a light this studio just paired."""
        existing = self.by_address(address)
        light = SavedLight(
            id=existing.id if existing else uuid.uuid4().hex[:10],
            name=name.strip()[:60] or (existing.name if existing else model_caps(radio_id).name),
            address=address.upper(), radio_id=radio_id.upper(), network=network_id,
            node_address=node_address, num_elements=num_elements, device_key=device_key,
            model_source="advert" if radio_id else "unknown", added=time.time(),
            x=existing.x if existing else None, y=existing.y if existing else None,
            channel=existing.channel if existing else None,
        )
        self.save_light(light)
        self.set_active(light.id)
        return light

    # -- what is nearby --------------------------------------------------------------------------

    def describe(self, nearby: Nearby, public_ids: dict[str, str] | None = None) -> dict[str, Any]:
        """A nearby light as the browser sees it, related to what we already know."""
        public_ids = self.network_ids_by_public_id() if public_ids is None else public_ids
        saved = self.by_address(nearby.address)
        radio_id = nearby.radio_id or (saved.radio_id if saved else "")
        caps = model_caps(radio_id)
        if nearby.state == "unpaired":
            relation = "unpaired"  # factory fresh, or a saved light that was reset
        elif saved is not None:
            relation = "saved"
        elif nearby.network_id and nearby.network_id in public_ids:
            relation = "your-network"
        else:
            relation = "elsewhere"
        return {
            "address": nearby.address, "name": nearby.name, "rssi": nearby.rssi, "radio_id": radio_id or None,
            "model": caps.name if caps.known else None, "kind": caps.kind if caps.known else None,
            "relation": relation, "light_id": saved.id if saved else None, "seen_at": nearby.seen_at,
        }
