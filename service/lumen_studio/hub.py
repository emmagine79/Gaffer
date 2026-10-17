"""The running studio: every saved light, the one mesh link that reaches them, and everyone watching.

Data flow, one direction each way:

    browser --ws--> commands -> fixture state / engine -> pump -> link -> mesh -> light
    light --mesh--> link -> Hub._on_access (by source address) -> fixture -> broadcast --ws--> browsers

Each light is a :class:`Fixture` with its own state and effect engine. Only
the lights on one mesh network are reachable at a time (the network of the
light being edited); a light on another network is a click away, and the
link moves over when it is chosen.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import re
import time
import uuid
from collections import deque
from collections.abc import Callable
from typing import Any

from godox_mesh_bt.crypto import k3
from godox_mesh_bt.state import MeshState

from .catalog import model_caps, models_index
from .effects import REGISTRY
from .effects.profile import effect_profile
from .fixture import Fixture, gel_key
from .lights import LightLibrary, SavedLight
from .link import LinkManager, Member, SequenceVault
from .mirror import ALL_PROPS, mirror
from .pairing import Pairer, pair_light
from .pump import CommandPump
from .scheduler import run_scheduler
from .state import LightState, StateError, apply_patch
from .store import Store
from .sync import (
    RECORD_CCT,
    RECORD_HSI,
    CctRecord,
    HsiRecord,
    expected_record,
    parse_onoff,
    parse_record,
)
from .transport import DemoLink

logger = logging.getLogger(__name__)

RESPONSE_PREFIX = bytes([0xF1, 0x11, 0x02])
#: After the app sends a command the light's records lag it briefly; readings
#: inside this window are treated as echoes, never as outside changes.
SETTLE_SECONDS = 1.2
BATTERY_INTERVAL = 120.0
#: Engine kinds that animate a light; a group mirrors them only when "effects" is synced.
ANIMATIONS = frozenset({"effect", "stream", "timeline"})
SYNC_PROPS = ("power", "brightness", "white", "colour", "effects")


#: A Bluetooth address: a MAC on Windows and Linux, a UUID on macOS.
ADDRESS = re.compile(r"^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$|^[0-9A-Fa-f]{8}-([0-9A-Fa-f]{4}-){3}[0-9A-Fa-f]{12}$")


def keys_problem(state: MeshState) -> str | None:
    """Why a keys file cannot be used, or None. Checked before anything is saved."""
    for name in ("network_key", "app_key"):
        try:
            if len(bytes.fromhex(getattr(state, name))) != 16:
                return f"{name} must be 16 bytes"
        except ValueError:
            return f"{name} is not hexadecimal"
    if state.device_key:
        try:
            if len(bytes.fromhex(state.device_key)) != 16:
                return "device_key must be 16 bytes"
        except ValueError:
            return "device_key is not hexadecimal"
    if not 0x0001 <= state.node_address <= 0x7FFF:
        return "node_address must be a unicast address, 1 to 0x7FFF"
    if not 1 <= state.num_elements <= 32:
        return "num_elements must be 1 to 32"
    if not 0 <= state.iv_index < 2**32 or not 0 <= state.sequence_number < 2**24:
        return "iv_index or sequence_number is out of range"
    return None


class HubError(ValueError):
    """Something the user asked for that cannot be done, with a message fit to show them."""


class Client:
    """One browser. State updates coalesce per light (latest wins); everything else queues."""

    def __init__(self) -> None:
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=512)
        self.pending_states: dict[str, dict[str, Any]] = {}
        self.visible = True
        self.selected: str | None = None
        self.wake = asyncio.Event()

    def push(self, message: dict[str, Any]) -> None:
        if message.get("type") == "state":
            self.pending_states[str(message.get("light"))] = message
        else:
            try:
                self.queue.put_nowait(message)
            except asyncio.QueueFull:
                return  # a stalled tab loses log noise, not correctness: state is separate
        self.wake.set()

    async def next(self) -> dict[str, Any]:
        while True:
            if self.pending_states:
                key = next(iter(self.pending_states))
                return self.pending_states.pop(key)
            if not self.queue.empty():
                return self.queue.get_nowait()
            self.wake.clear()
            await self.wake.wait()


class NoLink:
    """Stands in while there is no light to connect to."""

    def __init__(self, listener: Callable[[dict[str, Any]], None], detail: str = "") -> None:
        self._listener = listener
        self._stop = asyncio.Event()
        self.firmware: dict[str, Any] = {}
        self.detail = detail or "No lights yet. Pair one or import its keys."

    def snapshot(self) -> dict[str, Any]:
        return {"status": "no-light", "detail": self.detail, "address": None,
                "gateway": None, "connected_since": None, "latency_ms": None, "rssi": None, "sequence": 0,
                "sequence_budget": 0.0, "source": None, "interval_ms": None, "firmware": {}}

    def note_activity(self) -> None: ...
    def report_trouble(self, err: Exception) -> None: ...
    def check_budget(self) -> None: ...
    def reconnect_now(self) -> None: ...

    def stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        self._listener(self.snapshot())
        await self._stop.wait()


class Hub:
    def __init__(
        self,
        store: Store,
        library: LightLibrary,
        *,
        demo: bool,
        scanner: Any = None,
        pairer: Pairer | None = None,
        fps: float = 60.0,
    ) -> None:
        from .discovery import Scanner

        self.store = store
        self.library = library
        self.demo = demo
        self.fps = fps
        self.scanner = scanner if scanner is not None else Scanner()
        if pairer is None and demo:
            from .demo import demo_pair as pairer
        self._pairer: Pairer = pairer or pair_light
        self.clients: set[Client] = set()
        self.log: deque[dict[str, Any]] = deque(maxlen=300)
        self.fixtures: dict[str, Fixture] = {}
        self.controller: Any = None
        self.nearby: dict[str, dict[str, Any]] = {}
        self.scanning = False
        self.pairing: dict[str, Any] | None = None
        self.lab_until = 0.0  # log every reply briefly after a Lab request
        self._vaults: dict[str, SequenceVault] = {}
        self._engine_tasks: dict[str, asyncio.Task[Any]] = {}
        self._tasks: list[asyncio.Task[Any]] = []
        self._link_task: asyncio.Task[Any] | None = None
        self._started = False
        self._save_due = 0.0
        self._switch_lock = asyncio.Lock()

        for light in library.lights:
            self._add_fixture(light)
        active = library.active or (library.lights[0] if library.lights else None)
        self.network: str | None = active.network if active else None
        self.pump = CommandPump(model_caps(""), max_rate=float(store.settings["max_rate"]),
                                on_send_failure=self._on_send_failure)
        self.link: Any = self._make_link()

    # -- fixtures --------------------------------------------------------------------

    def _saved_state(self, light: SavedLight) -> LightState:
        saved = (self.store.settings.get("light_states") or {}).get(light.id)
        if saved:
            try:
                return LightState.model_validate(saved)
            except ValueError:
                logger.warning("saved state for %s invalid; starting fresh", light.name)
        return LightState()

    def _add_fixture(self, light: SavedLight) -> Fixture:
        fixture = Fixture(light, self._saved_state(light), on_engine_state=self._apply_engine,
                          on_engine_change=self._engine_changed, fps=self.fps)
        self.fixtures[light.id] = fixture
        if self._started:
            self._engine_tasks[light.id] = asyncio.create_task(fixture.engine.run())
        return fixture

    def _drop_fixture(self, light_id: str) -> None:
        fixture = self.fixtures.pop(light_id, None)
        task = self._engine_tasks.pop(light_id, None)
        if task is not None:
            task.cancel()
        if fixture is not None and self.on_network(fixture):
            self.pump.drop(fixture.node)

    def fixture(self, light_id: str | None) -> Fixture:
        if light_id is None:
            light_id = self.default_light_id()
        if light_id is None or light_id not in self.fixtures:
            raise HubError("no such light" if light_id else "there is no light yet")
        return self.fixtures[light_id]

    def default_light_id(self) -> str | None:
        active = self.library.active
        if active is not None and active.id in self.fixtures:
            return active.id
        return next(iter(self.fixtures), None)

    def on_network(self, fixture: Fixture) -> bool:
        return self.network is not None and fixture.light.network == self.network

    def _by_node(self) -> dict[int, Fixture]:
        return {f.node: f for f in self.fixtures.values() if self.on_network(f)}

    def _focus(self) -> list[Fixture]:
        """Lights someone is looking at right now."""
        ids = {c.selected or self.default_light_id() for c in self.clients if c.visible}
        return [self.fixtures[i] for i in ids if i in self.fixtures and self.on_network(self.fixtures[i])]

    # -- the link ----------------------------------------------------------------------

    def _vault(self, network: str) -> SequenceVault:
        if network not in self._vaults:
            self._vaults[network] = SequenceVault(self.library.network_path(network))
        return self._vaults[network]

    def _members(self) -> list[Member]:
        return [Member(f.id, f.light.address, f.node) for f in self.fixtures.values() if self.on_network(f)]

    def _preferred_light(self) -> SavedLight | None:
        for light_id in (self.library.active.id if self.library.active else None, *self.fixtures):
            if light_id in self.fixtures and self.on_network(self.fixtures[light_id]):
                return self.fixtures[light_id].light
        return None

    def _make_link(self) -> Any:
        if self.network is None or not self._members():
            return NoLink(self._link_changed)
        if self.demo:
            return DemoLink(
                gateway=self._preferred_light, nodes=lambda: [m.node_address for m in self._members()],
                on_connected=self._on_connected, on_disconnected=self._on_disconnected,
                listener=self._link_changed, on_access=self._on_access,
            )
        vault = self._vault(self.network)
        return LinkManager(
            vault,
            members=self._members,
            public_id=k3(bytes.fromhex(vault.state.network_key)).hex(),
            preferred=lambda: (light.address if (light := self._preferred_light()) else None),
            on_connected=self._on_connected,
            on_disconnected=self._on_disconnected,
            serial=self.pump.submit_aux,
            on_access=self._on_access,
            on_advert=self._on_advert,
            listener=self._link_changed,
            relay_ttl=lambda: int(self.store.settings.get("relay_ttl", 5)),
        )

    def _start_link(self) -> None:
        self.link = self._make_link()
        self._link_task = asyncio.create_task(self.link.run())

    async def _stop_link(self) -> None:
        self.link.stop()
        task, self._link_task = self._link_task, None
        if task is not None:
            try:
                await asyncio.wait_for(task, timeout=8)
            except (TimeoutError, asyncio.CancelledError):
                task.cancel()
            except Exception as err:  # noqa: BLE001 - it is going away either way
                logger.debug("link ended with %s", err)
        if self.controller is not None:
            self._on_disconnected()

    async def _relink(self, network: str | None) -> None:
        """Point the link at ``network`` (or none), dropping everything queued for the old one.

        Always ends with a link task running, whatever fails on the way: a hub
        left without one would ignore every later attempt to reconnect.
        """
        try:
            await self._stop_link()
        finally:
            self.pump.reset()
            self.network = network
            for fixture in self.fixtures.values():
                fixture.adopting = True  # read each light again before writing it
            try:
                self.link = self._make_link()
            except Exception as err:
                logger.exception("could not open network %s", network)
                self.link = NoLink(self._link_changed, f"Could not open this network's keys: {err}")
            self._link_task = asyncio.create_task(self.link.run())

    async def _move_to_network(self, network: str | None) -> None:
        """Point the link at another network (or none)."""
        if network == self.network and not isinstance(self.link, NoLink):
            return
        await self._relink(network)

    # -- lifecycle ------------------------------------------------------------------------

    async def start(self) -> None:
        self._started = True
        for light_id, fixture in self.fixtures.items():
            self._engine_tasks[light_id] = asyncio.create_task(fixture.engine.run())
        scheduler = run_scheduler(lambda: self.store.items("schedules"), self.fire_schedule)
        for coro in (self.pump.run(), self._broadcast_loop(), self._sync_loop(), self._battery_loop(), scheduler):
            self._tasks.append(asyncio.create_task(coro))
        self._link_task = asyncio.create_task(self.link.run())

    async def stop(self) -> None:
        self._save_states(force=True)
        await self._stop_link()
        for task in [*self._tasks, *self._engine_tasks.values()]:
            task.cancel()
        await asyncio.gather(*self._tasks, *self._engine_tasks.values(), return_exceptions=True)

    # -- link callbacks -------------------------------------------------------------------

    def _on_connected(self, controller: Any) -> None:
        self.controller = controller
        by_node = self._by_node()

        async def send(frame: bytes, node: int | None) -> None:
            await controller.send_payload(frame, dst=node)
            fixture = by_node.get(node) if node is not None else None
            if fixture is not None:
                fixture.sync.expect(expected_record(frame))
                fixture.last_control_at = time.monotonic()
            self.link.note_activity()

        self.pump.attach(send)
        for fixture in by_node.values():
            fixture.sync.reset()
            if fixture.adopting:
                asyncio.create_task(self._adopt(fixture))
            else:
                # Reconnect: the light may have lost power; re-assert its look.
                self.pump.submit(fixture.state, fixture.node, fixture.caps)
        asyncio.create_task(self._read_firmware())
        self._log("link", "connected")

    def _on_disconnected(self) -> None:
        self.controller = None
        self.pump.attach(None)
        self._log("link", "disconnected")

    def _on_send_failure(self, err: Exception) -> None:
        self._log("error", f"write failed: {err}")
        self.link.report_trouble(err)

    def _link_changed(self, snapshot: dict[str, Any]) -> None:
        self._broadcast({"type": "link", "link": snapshot})

    async def _read_firmware(self) -> None:
        controller = self.controller
        if controller is None:
            return
        try:
            mesh = await asyncio.wait_for(self.pump.submit_aux(controller.request_version), 4)
            mcu = await asyncio.wait_for(self.pump.submit_aux(controller.request_mcu_version), 4)
        except Exception as err:  # noqa: BLE001 - informational only
            logger.info("firmware read failed: %s", err)
            return
        self.link.firmware = {"mesh": mesh, "mcu": mcu}
        self._link_changed(self.link.snapshot())

    def _on_advert(self, address: str, radio_id: str) -> None:
        """A light on the network said what model it is."""
        light = self.library.by_address(address)
        if light is None or light.radio_id == radio_id or light.model_source == "manual":
            return
        if not model_caps(radio_id).known:
            return  # a garbled advert must not downgrade a known light to the default profile
        self._set_model(light.id, radio_id, source="advert")
        self._toast("info", f"{light.name} recognised as {model_caps(radio_id).name}")

    async def _adopt(self, fixture: Fixture) -> None:
        """First contact: take the light's real state instead of overwriting it."""
        started = time.monotonic()
        controller = self.controller
        records = (RECORD_CCT, RECORD_HSI) if fixture.caps.has_colour else (RECORD_CCT,)
        for record in records:
            await self._request(fixture, record)
        await asyncio.sleep(0.8)
        if self.controller is not controller or not self.on_network(fixture) or fixture.id not in self.fixtures:
            return  # the link moved on while we were reading; this answer belongs to no one now
        cct, hsi = fixture.readback["cct"], fixture.readback["hsi"]
        patch: dict[str, Any] | None = None
        # Only CCT and HSI have a live record; for RGBW, gel and effects the
        # saved state stays the best knowledge there is.
        if fixture.state.mode == "hsi" and hsi is not None:
            patch = HsiRecord(**hsi).patch()
        elif fixture.state.mode == "cct" and cct is not None:
            patch = CctRecord(**cct).patch()
        if fixture.last_control_at > started or fixture.engine.kind is not None:
            patch = None  # someone changed the light while we were reading it; theirs wins
        if patch is not None:
            try:
                self.set_state(fixture, apply_patch(fixture.state, patch, fixture.caps), "light", send=False,
                               mirror=False)
                self.pump.forget(fixture.node)
            except StateError as err:
                logger.info("light state not adoptable: %s", err)
        if cct is None and hsi is None:
            # Nothing came back: assert our state so the light matches what we show.
            self.pump.submit(fixture.state, fixture.node, fixture.caps)
        fixture.adopting = False
        self._log("sync", f"{fixture.light.name}: " + ("adopted its current state" if patch else "kept the saved state"))

    # -- inbound from the mesh ----------------------------------------------------------------

    def _on_access(self, src: int, payload: bytes) -> None:
        fixture = self._by_node().get(src)
        if fixture is None:
            self._log("rx", f"from unknown node 0x{src:04x}: {payload.hex()}")
            return
        now = time.monotonic()
        fixture.heard()
        if parse_onoff(payload) is not None:
            # The heartbeat says "on" even when the light is off: liveness only.
            fixture.readback["heartbeat_at"] = time.time()
            self._broadcast({"type": "heartbeat", "light": fixture.id, "at": fixture.readback["heartbeat_at"]})
            return
        if payload[:3] != RESPONSE_PREFIX:
            self._log("rx", f"{fixture.light.name}: {payload.hex()}")
            return
        record = parse_record(payload[3:])
        if record is None:
            if payload[3:4] != b"\xa6":  # battery replies are read by the library itself
                self._log("rx", f"{fixture.light.name}: reply {payload[3:].hex(' ')}")
            return
        if now < self.lab_until:
            self._log("rx", f"{fixture.light.name}: reply {payload[3:].hex(' ')} = {record}")
        key = "cct" if isinstance(record, CctRecord) else "hsi"
        sent_at = fixture.request_at.pop(RECORD_CCT if key == "cct" else RECORD_HSI, None)
        if sent_at is not None:
            fixture.readback["latency_ms"] = round((now - sent_at) * 1000, 1)
        fixture.readback[key] = {k: getattr(record, k) for k in record.__slots__}
        self._broadcast({"type": "readback", "light": fixture.id, "readback": fixture.readback})

        if fixture.adopting or fixture.engine.kind is not None or now - fixture.last_control_at < SETTLE_SECONDS:
            fixture.sync.baseline(record)
            return
        patch = fixture.sync.observe(record, fixture.state)
        if patch is None:
            return
        try:
            self.set_state(fixture, apply_patch(fixture.state, patch, fixture.caps), "light", send=False)
        except StateError as err:
            logger.info("ignoring out-of-range reading: %s", err)
            return
        self.pump.forget(fixture.node)
        self._log("sync", f"{fixture.light.name} changed on the light: {patch}")
        self._toast("sync", f"Picked up a change made on {fixture.light.name}")

    async def _request(self, fixture: Fixture, record: int) -> None:
        controller = self.controller
        if controller is None:
            return
        fixture.request_at[record] = time.monotonic()
        try:
            await asyncio.wait_for(
                self.pump.submit_aux(lambda: controller.request_record(record, dst=fixture.node)), 3
            )
        except Exception as err:  # noqa: BLE001
            logger.debug("record request failed: %s", err)

    async def _sync_loop(self) -> None:
        """Poll the live records of the lights being watched, while the app is not driving them."""
        flip = False
        while True:
            interval = float(self.store.settings.get("sync_interval") or 0)
            await asyncio.sleep(interval if interval > 0 else 2.0)
            if interval <= 0 or self.controller is None:
                continue
            flip = not flip
            now = time.monotonic()
            for fixture in self._focus():
                if fixture.engine.kind is not None or fixture.adopting or now - fixture.last_control_at < SETTLE_SECONDS:
                    continue
                hsi = fixture.caps.has_colour and fixture.state.mode == "hsi" and not flip
                await self._request(fixture, RECORD_HSI if hsi else RECORD_CCT)

    async def _battery_loop(self) -> None:
        while True:
            await asyncio.sleep(5.0)
            controller = self.controller
            if controller is None:
                continue
            for fixture in list(self.fixtures.values()):
                if not (fixture.caps.battery and self.on_network(fixture)):
                    continue
                last = (fixture.device.get("battery") or {}).get("at", 0)
                if time.time() - last < BATTERY_INTERVAL:
                    continue
                try:
                    reply = await asyncio.wait_for(self.pump.submit_aux(
                        lambda f=fixture, c=controller: c.request_battery(dst=f.node, timeout=3)), 5)
                except Exception as err:  # noqa: BLE001 - a light on mains power may not answer
                    logger.debug("battery read failed for %s: %s", fixture.light.name, err)
                    fixture.device["battery"] = {"percent": None, "at": time.time()}
                    continue
                fixture.device["battery"] = {
                    "percent": reply.power_percent, "hours": reply.hour, "minutes": reply.minute,
                    "state": reply.state, "at": time.time(),
                }
                self._broadcast({"type": "device", "light": fixture.id, "device": fixture.device})

    # -- schedules ----------------------------------------------------------------------------

    def fire_schedule(self, schedule: dict[str, Any]) -> None:
        targets = schedule.get("lights") or [f.id for f in self.fixtures.values() if self.on_network(f)]
        name = schedule.get("name", "schedule")
        for light_id in targets:
            if light_id in self.fixtures:
                self._run_schedule_on(self.fixtures[light_id], schedule)
        self._log("schedule", f"ran {name}")
        self._toast("info", f"Schedule: {name}")

    def _run_schedule_on(self, fixture: Fixture, schedule: dict[str, Any]) -> None:
        from .adapt import adapt_state
        from .state import merge_patch

        fixture.stream_source = None  # a schedule takes the light over like any command
        action = schedule.get("action")
        engine = fixture.engine
        if action == "sunrise":
            engine.start_effect("sunrise", {"minutes": float(schedule.get("minutes") or 15)})
        elif action == "effect":
            engine.start_effect(str(schedule.get("target")), {})
        elif action == "scene":
            scene = next((s for s in self.store.items("scenes") if s["id"] == schedule.get("target")), None)
            if scene is None:
                raise KeyError(f"scene {schedule.get('target')} no longer exists")
            if scene.get("effect"):
                engine.start_effect(scene["effect"], scene.get("params") or {})
            else:
                engine.stop(restore=False)
                target = adapt_state(LightState.model_validate(merge_patch(fixture.state, scene["state"])), fixture.caps)
                engine.start_transition(target, 3.0)
        elif action in ("on", "off"):
            engine.stop(restore=False)
            engine.start_transition(fixture.state.model_copy(update={"power": action == "on"}), 3.0)
        else:
            raise ValueError(f"unknown action {action!r}")

    # -- state --------------------------------------------------------------------------------

    def set_state(self, fixture: Fixture, state: LightState, source: str, *, send: bool = True,
                  mirror: bool = True) -> None:
        fixture.state = state
        fixture.state_source = source
        fixture.dirty = True
        if send and self.on_network(fixture):
            self.pump.submit(state, fixture.node, fixture.caps)
        self._save_due = self._save_due or time.monotonic() + 2.0
        if mirror:
            self._mirror_from(fixture)

    def _apply_engine(self, fixture: Fixture, state: LightState) -> None:
        self.set_state(fixture, state, "engine")

    def _engine_changed(self, fixture: Fixture, status: dict[str, Any]) -> None:
        self._broadcast({"type": "engine", "light": fixture.id, "engine": status})

    def _save_states(self, *, force: bool = False) -> None:
        if not force and (self._save_due == 0 or time.monotonic() < self._save_due):
            return
        self._save_due = 0.0
        states = {**(self.store.settings.get("light_states") or {})}
        states.update({light_id: f.state.model_dump() for light_id, f in self.fixtures.items()})
        self.store.update_settings({"light_states": {k: v for k, v in states.items() if k in self.fixtures}})

    # -- sync groups --------------------------------------------------------------------------

    @property
    def groups(self) -> list[dict[str, Any]]:
        return list(self.store.settings.get("groups") or [])

    def group_of(self, light_id: str) -> dict[str, Any] | None:
        for group in self.groups:
            members = [m for m in group.get("members", []) if m in self.fixtures]
            if group.get("enabled") and light_id in members and len(members) > 1:
                return group
        return None

    def _mirror_from(self, leader: Fixture) -> None:
        group = self.group_of(leader.id)
        if group is None:
            return
        props = frozenset(group.get("props") or ALL_PROPS)
        if leader.engine.kind in ANIMATIONS and "effects" not in props:
            return
        for member_id in group["members"]:
            follower = self.fixtures.get(member_id)
            if follower is None or follower is leader or not self.on_network(follower):
                continue
            new = mirror(leader.state, follower.state, props, follower.caps, leader_caps=leader.caps)
            if new == follower.state:
                continue
            if follower.engine.kind is not None:
                follower.engine.stop(restore=False)  # a follower's own effect yields to the group
            self.set_state(follower, new, "group", mirror=False)

    def save_group(self, group: dict[str, Any], leader: str | None = None) -> dict[str, Any]:
        """Create or update a group. Joining or re-enabling lines the members up behind ``leader``."""
        name = str(group.get("name") or "").strip()[:40] or "Group"
        members = [m for m in dict.fromkeys(group.get("members") or []) if m in self.fixtures]
        props = [p for p in SYNC_PROPS if p in (group.get("props") or SYNC_PROPS)]
        clean = {
            "id": str(group.get("id") or uuid.uuid4().hex[:8]), "name": name, "members": members,
            "props": props, "enabled": bool(group.get("enabled", True)),
        }
        # A light follows one group: joining this one takes it out of any other.
        ordered = [
            clean if g["id"] == clean["id"] else {**g, "members": [m for m in g["members"] if m not in members]}
            for g in self.groups
        ]
        before = next((g for g in self.groups if g["id"] == clean["id"]), None)
        if not any(g["id"] == clean["id"] for g in ordered):
            ordered.append(clean)
        self.store.update_settings({"groups": ordered})
        self._broadcast({"type": "groups", "groups": ordered})
        changed = before is None or any(before.get(k) != clean[k] for k in ("members", "props", "enabled"))
        if changed and clean["enabled"] and len(members) > 1:
            # Line everyone up behind the light being worked on, not whichever joined first;
            # a rename alone changes no light.
            first = leader if leader in members else members[0]
            self._mirror_from(self.fixtures[first])
        return clean

    def delete_group(self, group_id: str) -> None:
        remaining = [g for g in self.groups if g["id"] != group_id]
        self.store.update_settings({"groups": remaining})
        self._broadcast({"type": "groups", "groups": remaining})

    def match(self, leader_id: str, targets: list[str], props: list[str]) -> None:
        """One-off: copy ``props`` from one light to others, without linking them."""
        leader = self.fixture(leader_id)
        chosen = frozenset(p for p in props if p in SYNC_PROPS) or ALL_PROPS
        for light_id in targets:
            follower = self.fixtures.get(light_id)
            if follower is None or follower is leader:
                continue
            follower.engine.stop(restore=False)
            self.set_state(follower, mirror(leader.state, follower.state, chosen, follower.caps,
                                            leader_caps=leader.caps), "group", mirror=False)

    # -- managing lights --------------------------------------------------------------------------

    async def select(self, client: Client, light_id: str, *, connect: bool = False) -> None:
        """Make a light the one this browser edits; with ``connect``, move the link to its network.

        Moving networks drops every light on the current one, so it happens only
        when asked for, never as a side effect of looking at a light.
        """
        fixture = self.fixture(light_id)
        client.selected = light_id
        if self.library.active is None or self.library.active.id != light_id:
            self.library.set_active(light_id)
        if connect and not self.on_network(fixture):
            self._toast("info", f"Moving to {fixture.light.name}'s network")
            async with self._switch_lock:
                await self._move_to_network(fixture.light.network)

    async def scan(self, seconds: float = 6.0) -> list[dict[str, Any]]:
        if self.scanning:
            return list(self.nearby.values())
        public_ids = self.library.network_ids_by_public_id()
        self.scanning = True
        self.nearby = {}
        self._broadcast({"type": "nearby", "nearby": [], "scanning": True})

        def found(nearby: Any) -> None:
            self.nearby[nearby.address] = self.library.describe(nearby, public_ids)
            self._broadcast({"type": "nearby", "nearby": list(self.nearby.values()), "scanning": True})

        try:
            await self.scanner.scan(seconds, found)
        finally:
            self.scanning = False
            self._broadcast({"type": "nearby", "nearby": list(self.nearby.values()), "scanning": False})
        return list(self.nearby.values())

    def _pairing_step(self, address: str, step: str, error: str = "") -> None:
        self.pairing = {"address": address, "step": step, "error": error, "at": time.time()}
        self._broadcast({"type": "pairing", "pairing": self.pairing})

    async def pair(self, client: Client, address: str, name: str = "", radio_id: str = "") -> SavedLight:
        address = address.upper()
        if self.pairing and self.pairing["step"] not in ("done", "failed"):
            raise HubError("already pairing a light; let that finish first")
        seen = self.nearby.get(address)
        # Only a light this studio just heard asking to be paired: pairing hands
        # over the network key, so the address must not come from anywhere else.
        if seen is None:
            raise HubError("scan first: only a light found ready to pair can be paired")
        if seen.get("relation") != "unpaired":
            raise HubError("that light is already on a network; factory-reset it to pair it here")
        radio = (radio_id or seen.get("radio_id") or "").upper()
        network = self.library.default_network()
        vault = self._vault(network)
        node = self.library.next_node_address(network)
        self._pairing_step(address, "starting")
        async with self._switch_lock:
            for fixture in self.fixtures.values():
                fixture.engine.stop(restore=False)
            self._save_states(force=True)
            await self._stop_link()  # the radio is needed, and the counter must not be shared
            try:
                paired = await self._pairer(
                    self.scanner.devices.get(address, address), address=address, vault=vault,
                    node_address=node, on_step=lambda step: self._pairing_step(address, step),
                )
            except Exception as err:
                self._pairing_step(address, "failed", str(err) or type(err).__name__)
                await self._relink(self.network)  # back to the lights we had
                raise HubError(f"pairing failed: {err}") from err
            light = self.library.add_paired(
                network_id=network, address=address, radio_id=radio, node_address=node,
                num_elements=paired.num_elements, device_key=paired.device_key, name=name,
            )
            if light.id in self.fixtures:
                self._drop_fixture(light.id)  # a saved light that was reset and paired again
            fixture = self._add_fixture(light)
            client.selected = light.id
            await self._relink(network)
            fixture.adopting = False  # fresh from the factory: our state is the truth
        self._pairing_step(address, "done")
        self.nearby.pop(address, None)
        self._broadcast_lights()
        self._log("lights", f"paired {light.name} as node 0x{node:04x}")
        return light

    async def import_keys(self, client: Client, keys: Any, address: str, name: str = "",
                          radio_id: str = "") -> SavedLight:
        if not isinstance(keys, dict):
            raise HubError("the keys file should be a mesh_state.json object")
        try:
            state = MeshState.from_json(json.dumps(keys))
        except (ValueError, TypeError, KeyError) as err:
            raise HubError(f"those keys are not usable: {err}") from err
        problem = keys_problem(state)
        if problem:
            raise HubError(f"those keys are not usable: {problem}")
        if not ADDRESS.match(address.strip()):
            raise HubError("choose which nearby light these keys belong to (a Bluetooth address)")
        if radio_id and not model_caps(radio_id).known:
            raise HubError(f"{radio_id} is not a model in the catalogue")
        seen = self.nearby.get(address.upper()) or {}
        radio = (radio_id or seen.get("radio_id") or "").upper()
        try:
            light = self.library.import_keys(state, address=address, name=name, radio_id=radio,
                                             source="manual" if radio_id else "advert")
        except ValueError as err:
            raise HubError(str(err)) from err
        if light.id in self.fixtures:
            self._drop_fixture(light.id)
        self._add_fixture(light)
        client.selected = light.id
        async with self._switch_lock:
            await self._relink(light.network)
        self._broadcast_lights()
        self._log("lights", f"imported keys for {light.name}")
        return light

    def rename(self, light_id: str, name: str) -> None:
        try:
            light = self.library.rename(light_id, name)
        except (ValueError, KeyError) as err:
            raise HubError(str(err)) from err
        self.fixture(light_id).light = light
        self._broadcast_lights()

    def _set_model(self, light_id: str, radio_id: str, *, source: str) -> None:
        light = self.library.set_model(light_id, radio_id, source=source)
        fixture = self.fixture(light_id)
        fixture.light = light
        fixture.engine.stop(restore=False)
        fixture.use_caps(model_caps(radio_id))
        if self.on_network(fixture):
            self.pump.forget(fixture.node)
            self.pump.submit(fixture.state, fixture.node, fixture.caps)
        self._broadcast_lights()

    def set_model(self, light_id: str, radio_id: str) -> None:
        if not radio_id or not model_caps(radio_id).known:
            raise HubError("pick a model from the list")
        self._set_model(light_id, radio_id, source="manual")

    def place(self, light_id: str, x: float, y: float) -> None:
        light = self.library.get(light_id)
        moved = self.library.save_light(dataclasses.replace(light, x=round(min(1.0, max(0.0, x)), 4),
                                                            y=round(min(1.0, max(0.0, y)), 4)))
        self.fixture(light_id).light = moved
        self._broadcast({"type": "placed", "light": light_id, "x": moved.x, "y": moved.y})

    async def forget(self, light_id: str) -> None:
        fixture = self.fixture(light_id)
        network = fixture.light.network
        self._drop_fixture(light_id)
        self.library.forget(light_id)
        groups = [{**g, "members": [m for m in g["members"] if m != light_id]} for g in self.groups]
        states = {k: v for k, v in (self.store.settings.get("light_states") or {}).items() if k != light_id}
        self.store.update_settings({"groups": groups, "light_states": states})
        for client in self.clients:
            if client.selected == light_id:
                client.selected = None
        if network == self.network:
            # Stay on this network while it has lights (the link may have gone
            # through the one just forgotten); only an emptied network moves on.
            same = [f for f in self.fixtures.values() if f.light.network == network]
            nxt = network if same else (self.fixtures[d].light.network if (d := self.default_light_id()) else None)
            async with self._switch_lock:
                await self._relink(nxt)
        self._broadcast({"type": "groups", "groups": groups})
        self._broadcast_lights()
        self._log("lights", f"forgot {fixture.light.name}")

    async def power_all(self, on: bool, fade: float = 0.0) -> None:
        for fixture in self.fixtures.values():
            if not self.on_network(fixture):
                continue
            fixture.engine.stop(restore=False)
            target = fixture.state.model_copy(update={"power": on})
            if fade > 0:
                fixture.engine.start_transition(target, fade, "inout")
            else:
                self.set_state(fixture, target, "app", mirror=False)

    # -- outbound to browsers ------------------------------------------------------------------

    def _broadcast(self, message: dict[str, Any]) -> None:
        for client in self.clients:
            client.push(message)

    def _toast(self, kind: str, text: str) -> None:
        self._broadcast({"type": "toast", "kind": kind, "text": text})

    def _log(self, kind: str, text: str) -> None:
        entry = {"t": time.time(), "kind": kind, "text": text}
        self.log.append(entry)
        self._broadcast({"type": "log", "entry": entry})

    def lights_view(self) -> dict[str, Any]:
        """Every light with its abilities and state, and the gel tables they use."""
        tables: dict[str, list[dict[str, Any]]] = {}
        for fixture in self.fixtures.values():
            key = gel_key(fixture.caps)
            if key is not None and key not in tables:
                tables[key] = list(fixture.caps.gel_table())
        return {
            "lights": [{**f.view(), "online": self.on_network(f)} for f in self.fixtures.values()],
            "gel_tables": tables,
            "network": self.network,
        }

    def _broadcast_lights(self) -> None:
        self._broadcast({"type": "lights", **self.lights_view()})

    def stats(self) -> dict[str, Any]:
        return {
            "pump": self.pump.stats.to_dict(time.monotonic()),
            "link": self.link.snapshot(),
            "clients": len(self.clients),
        }

    async def _broadcast_loop(self) -> None:
        last_stats = 0.0
        while True:
            await asyncio.sleep(1 / 30)
            for fixture in list(self.fixtures.values()):
                if fixture.dirty:
                    fixture.dirty = False
                    self._broadcast({"type": "state", "light": fixture.id, "state": fixture.state.model_dump(),
                                     "source": fixture.state_source})
            now = time.monotonic()
            if now - last_stats > 1.0:
                last_stats = now
                self._broadcast({"type": "stats", "stats": self.stats(),
                                 "reachable": {f.id: f.reachable for f in self.fixtures.values()}})
                self._save_states()
                for fixture in list(self.fixtures.values()):
                    if fixture.engine.expire_stream():
                        fixture.stream_source = None
                        self._log("sync", f"{fixture.light.name}: the music or screen source went quiet; holding the last look")
                self.link.check_budget()

    def hello(self, client: Client) -> dict[str, Any]:
        return {
            "type": "hello",
            "selected": client.selected or self.default_light_id(),
            **self.lights_view(),
            "effects": [{**e.to_dict(), **effect_profile(e.id)} for e in REGISTRY.values()],
            "models": list(models_index()),
            "groups": self.groups,
            "link": self.link.snapshot(),
            "store": self.store.snapshot(),
            "log": list(self.log)[-80:],
            "demo": self.demo,
            "nearby": list(self.nearby.values()),
            "scanning": self.scanning,
            "pairing": self.pairing,
        }
