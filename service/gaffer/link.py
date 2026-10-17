"""Holding one Bluetooth Mesh connection open, and getting it back when it drops.

Workarounds that live here, each measured on a real ML100R:

* **Windows lookup.** WinRT often cannot connect to a bare address string for a
  light that advertises intermittently, so the device is found by scanning
  first and the connection is opened on the found object.
* **One link, many lights.** The connection goes to one light, the gateway,
  and reaches the others by relaying through it, as Bluetooth Mesh intends.
  The scan recognises the gateway by address or by its network's public id.
* **Slow connect.** The library waits 2 s for a network beacon this light never
  sends; the wait is cut to 0.5 s.
* **Drop detection.** Bleak's disconnect callback wakes the supervisor at once
  instead of waiting for the next failed write.
* **Sequence numbers.** The library rewrites ``mesh_state.json`` after every
  command. A :class:`SequenceVault` instead persists a high-water mark well
  ahead of use, so the disk sees one write per block and a crash can never
  reuse a number the light has already accepted.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
import os
import time
from collections.abc import Awaitable, Callable
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from godox_mesh_bt import GodoxController, StatusTimeout
from godox_mesh_bt.state import MeshState

from .discovery import MESH_PROXY, radio_id_from_manufacturer
from .transport import AccessListener, StudioController

logger = logging.getLogger(__name__)

SEQUENCE_SPACE = 1 << 24  # 24-bit mesh sequence numbers
DEFAULT_RESERVE = 1024
#: Rotate to a fresh source address well before the counter can run out.
ROTATE_AT = SEQUENCE_SPACE - (1 << 20)
#: Source addresses the studio rotates through. Replay protection is tracked
#: per source address, so each one is a fresh 16.7 M-command budget; verified on
#: an ML100R (2026-10-03): a command from a new source at sequence 0 was accepted.
ROTATION_BASE = 0x0100
ROTATION_LAST = 0x7EFF


class LinkStatus(StrEnum):
    IDLE = "idle"
    SCANNING = "scanning"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    BACKOFF = "backoff"
    STOPPED = "stopped"


class SequenceVault:
    """Persist mesh state with the sequence number reserved ahead of use."""

    def __init__(self, path: Path, *, reserve: int = DEFAULT_RESERVE) -> None:
        self.path = path
        self.reserve = reserve
        loaded = MeshState.load(path)
        self.state = loaded
        self._high_water = loaded.sequence_number
        self._persist_ahead(loaded)

    def _persist_ahead(self, state: MeshState) -> None:
        mark = min(state.sequence_number + self.reserve, SEQUENCE_SPACE - 1)
        # Write-then-rename: a crash mid-write must never truncate the keys file.
        tmp = self.path.with_name(self.path.name + ".tmp")
        dataclasses.replace(state, sequence_number=mark).save(tmp)
        os.replace(tmp, self.path)
        self._high_water = mark

    def fresh_session(self) -> MeshState:
        """State for a new connection, starting at the persisted high-water mark.

        A write can fail after the light already accepted it, leaving the
        counter one behind what the light has seen. Starting each session at
        the reserved mark (never used) makes that impossible to replay, at a
        cost of at most one reserve block per reconnect.
        """
        self.state = dataclasses.replace(self.state, sequence_number=self._high_water)
        self._persist_ahead(self.state)
        return self.state

    def write(self, state: MeshState) -> None:
        """The controller's ``state_writer``: called after every send."""
        if state.provisioner_address != self.state.provisioner_address:
            return  # a straggler from before a source rotation; never let it rewind the vault
        self.state = state
        if state.sequence_number >= self._high_water:
            self._persist_ahead(state)

    @property
    def needs_rotation(self) -> bool:
        return self.state.sequence_number >= ROTATE_AT

    def rotate(self) -> int:
        """Switch to the next unused source address, starting its counter at 0."""
        current = self.state.provisioner_address
        nxt = current + 1 if ROTATION_BASE <= current < ROTATION_LAST else ROTATION_BASE
        self.state = dataclasses.replace(self.state, provisioner_address=nxt, sequence_number=0)
        self._persist_ahead(self.state)
        logger.warning("sequence budget spent on 0x%04x; rotated to source 0x%04x", current, nxt)
        return nxt

    @property
    def used(self) -> int:
        return self.state.sequence_number

    @property
    def budget_fraction(self) -> float:
        return self.state.sequence_number / SEQUENCE_SPACE


class Transport(Protocol):
    """What the rest of the studio needs from a connected light."""

    async def send_payload(self, payload: bytes) -> None: ...
    async def request_status(self, *, timeout: float = ...) -> Any: ...
    async def request_version(self) -> int: ...
    async def request_mcu_version(self) -> str: ...
    async def set_fan_mode(self, mode: int) -> None: ...
    async def send_v2_command_raw(self, frame: bytes) -> None: ...


Listener = Callable[[dict[str, Any]], None]
#: Runs a job on the pump's serial queue. Every use of the controller must go
#: through it: ``send_payload`` reads the sequence number, awaits the write and
#: only then advances it, so two concurrent sends would reuse a number and the
#: light's replay protection would silently drop the second.
Serial = Callable[[Callable[[], Awaitable[Any]]], Awaitable[Any]]


@dataclasses.dataclass(frozen=True, slots=True)
class Member:
    """A light on the network this link serves: where it is and what it answers to."""

    id: str
    address: str
    node_address: int


class LinkManager:
    """Supervises the connection to one mesh network: find a gateway, connect, watch, reconnect.

    Any light on the network can be the gateway; every other light is reached
    through it. The preferred light (the one being edited) is chosen when it is
    heard within a moment, since commands to the gateway itself are the
    fastest; otherwise the strongest light on the network wins, so one light
    switched off never cuts the studio off from the rest.
    """

    def __init__(
        self,
        vault: SequenceVault,
        *,
        members: Callable[[], list[Member]],
        public_id: str,
        preferred: Callable[[], str | None],
        on_connected: Callable[[Transport], None],
        on_disconnected: Callable[[], None],
        serial: Serial,
        on_access: AccessListener | None = None,
        on_advert: Callable[[str, str], None] | None = None,
        listener: Listener | None = None,
        relay_ttl: Callable[[], int] = lambda: 5,
        scan_timeout: float = 20.0,
        prefer_wait: float = 3.0,
        keepalive_interval: float = 15.0,
        idle_before_keepalive: float = 5.0,
    ) -> None:
        self.vault = vault
        self._members = members
        self._public_id = public_id
        self._preferred = preferred
        self._on_connected = on_connected
        self._on_disconnected = on_disconnected
        self._listener = listener
        self._serial = serial
        self._on_access = on_access
        self._on_advert = on_advert
        self._relay_ttl = relay_ttl
        self.interval_ms: float | None = None
        self._param_request: Any = None  # must stay referenced, or Windows reverts it
        self.scan_timeout = scan_timeout
        self.prefer_wait = prefer_wait
        self.keepalive_interval = keepalive_interval
        self.idle_before_keepalive = idle_before_keepalive
        self.status = LinkStatus.IDLE
        self.detail = ""
        self.address: str | None = None
        self.gateway: str | None = None
        self.connected_since: float | None = None
        self.last_rx: float | None = None
        self.last_tx: float = 0.0
        self.latency_ms: float | None = None
        self.rssi: int | None = None
        self.firmware: dict[str, Any] = {}
        self._controller: GodoxController | None = None
        self._dropped = asyncio.Event()
        self._stop = asyncio.Event()
        self._kick = asyncio.Event()
        self._failures = 0
        #: Lights that just failed to connect, with when to try them first again.
        self._avoid: dict[str, float] = {}

    # -- public ----------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        return {
            "status": str(self.status),
            "detail": self.detail,
            "address": self.address,
            "gateway": self.gateway,
            "connected_since": self.connected_since,
            "latency_ms": self.latency_ms,
            "rssi": self.rssi,
            "sequence": self.vault.used,
            "sequence_budget": round(self.vault.budget_fraction, 6),
            "source": self.vault.state.provisioner_address,
            "interval_ms": self.interval_ms,
            "firmware": self.firmware,
        }

    def note_activity(self) -> None:
        self.last_tx = time.monotonic()

    def check_budget(self) -> None:
        """Reconnect onto a fresh source address once the current one is nearly spent."""
        if self.vault.needs_rotation and self._controller is not None:
            self._dropped.set()

    def report_trouble(self, err: Exception) -> None:
        """Called by the pump when a write fails: treat the link as dropped."""
        logger.info("link trouble reported: %s", err)
        self._dropped.set()

    def reconnect_now(self) -> None:
        self._failures = 0
        self._kick.set()
        self._dropped.set()

    def stop(self) -> None:
        self._stop.set()
        self._kick.set()
        self._dropped.set()

    # -- supervisor --------------------------------------------------------------

    def _set(self, status: LinkStatus, detail: str = "") -> None:
        self.status = status
        self.detail = detail
        if self._listener is not None:
            self._listener(self.snapshot())

    async def run(self) -> None:
        while not self._stop.is_set():
            try:
                await self._session()
                self._failures = 0
            except Exception as err:  # noqa: BLE001 - any failure means retry with backoff
                self._failures += 1
                logger.warning("link attempt failed: %s", err)
                self.detail = f"{type(err).__name__}: {err}"
            finally:
                await self._teardown()
            if self._stop.is_set():
                break
            delay = min(30.0, 1.0 * 2 ** min(self._failures, 5)) if self._failures else 1.0
            self._set(LinkStatus.BACKOFF, f"retrying in {delay:.0f}s. {self.detail}")
            self._kick.clear()
            try:
                await asyncio.wait_for(self._kick.wait(), timeout=delay)
            except TimeoutError:
                pass
        self._set(LinkStatus.STOPPED)

    async def _find_gateway(self) -> tuple[Any, Member | None, int | None]:
        """Scan for lights on this network; return the device to connect through."""
        from bleak import BleakScanner

        members = {m.address: m for m in self._members()}
        heard: dict[str, tuple[Any, int | None]] = {}

        def on_adv(device: Any, adv: Any) -> None:
            address = device.address.upper()
            if address in members and self._on_advert is not None:
                radio_id = radio_id_from_manufacturer(
                    {int(k): bytes(v) for k, v in (adv.manufacturer_data or {}).items()}
                )
                if radio_id:
                    self._on_advert(address, radio_id)
            proxy = bytes((adv.service_data or {}).get(MESH_PROXY, b""))
            on_network = len(proxy) >= 9 and proxy[0] == 0 and proxy[1:9].hex() == self._public_id
            # Only a light offering the proxy service can be a gateway: a saved
            # light that was reset advertises provisioning instead, and would refuse.
            is_proxy = bool(proxy) or MESH_PROXY in {u.lower() for u in (adv.service_uuids or ())}
            if on_network or (address in members and is_proxy):
                heard[address] = (device, adv.rssi)

        self._set(LinkStatus.SCANNING, "looking for your lights")
        started = time.monotonic()
        async with BleakScanner(detection_callback=on_adv):
            while not self._stop.is_set():
                await asyncio.sleep(0.1)
                elapsed = time.monotonic() - started
                preferred = self._preferred()
                if preferred is not None and preferred in heard and not self._avoided(preferred):
                    break
                if heard and elapsed >= self.prefer_wait:
                    break
                if elapsed >= self.scan_timeout:
                    break
        if self._stop.is_set():
            return None, None, None
        if not heard:
            raise TimeoutError(f"no light on this network seen in {self.scan_timeout:.0f}s; are they on and in range?")
        preferred = self._preferred()
        usable = [a for a in heard if not self._avoided(a)] or list(heard)
        address = preferred if preferred in usable else max(usable, key=lambda a: heard[a][1] or -999)
        device, rssi = heard[address]
        return device, members.get(address), rssi

    def _avoided(self, address: str) -> bool:
        return self._avoid.get(address, 0.0) > time.monotonic()

    async def _session(self) -> None:
        from bleak import BleakClient

        device, member, rssi = await self._find_gateway()
        if device is None:
            return
        self.address = device.address.upper()
        self.gateway = member.id if member else None
        self.rssi = rssi
        self.last_rx = time.monotonic()

        if self.vault.needs_rotation:
            self.vault.rotate()
        self._set(LinkStatus.CONNECTING, f"connecting (RSSI {self.rssi} dBm)")
        loop = asyncio.get_running_loop()
        self._dropped.clear()

        def client_factory(_address: str) -> BleakClient:
            return BleakClient(
                device,
                timeout=20.0,
                disconnected_callback=lambda _c: loop.call_soon_threadsafe(self._dropped.set),
            )

        session = self.vault.fresh_session()
        if member is not None:
            session = dataclasses.replace(session, node_address=member.node_address)
        controller = StudioController(
            self.address,
            client_factory=client_factory,
            state=session,
            state_writer=self.vault.write,
            beacon_wait_timeout=0.5,
            proxy_config_ack_timeout=2.0,
            on_access=self._tap,
            gateway_node=member.node_address if member else None,
            relay_ttl=self._relay_ttl(),
        )
        started = time.monotonic()
        try:
            await controller.connect()
        except Exception:
            # Try another light on the network first next time, so one light that
            # will not take a connection does not cut the studio off from the rest.
            self._avoid[self.address] = time.monotonic() + 60.0
            with contextlib.suppress(Exception):
                await asyncio.wait_for(controller.disconnect(), timeout=4)
            raise
        except BaseException:
            # The BLE link may be up even though mesh setup failed; close it,
            # or the light stays busy and refuses the next attempt.
            with contextlib.suppress(Exception):
                await asyncio.wait_for(controller.disconnect(), timeout=4)
            raise
        self._tune(controller)
        self._controller = controller
        self.connected_since = time.time()
        self.last_rx = time.monotonic()
        self._set(LinkStatus.CONNECTED, f"connected in {time.monotonic() - started:.1f}s")
        self._on_connected(controller)
        keepalive = asyncio.create_task(self._keepalive(controller))
        try:
            await self._dropped.wait()
        finally:
            keepalive.cancel()

    async def _teardown(self) -> None:
        controller, self._controller = self._controller, None
        self._param_request = None
        self.interval_ms = None
        self.gateway = None
        if controller is None:
            return
        self._on_disconnected()
        self.connected_since = None
        try:
            await asyncio.wait_for(controller.disconnect(), timeout=5)
        except Exception as err:  # noqa: BLE001 - already gone is fine
            logger.debug("disconnect: %s", err)

    async def probe(self, controller: GodoxController) -> Any:
        """One serialised readback round-trip; records latency. Raises StatusTimeout."""

        async def job() -> Any:
            started = time.monotonic()
            status = await controller.request_status(timeout=2.5)
            self.latency_ms = round((time.monotonic() - started) * 1000, 1)
            self.last_rx = time.monotonic()
            return status

        return await self._serial(job)

    def _tune(self, controller: StudioController) -> None:
        """Ask Windows for its fastest connection interval.

        Measured on an ML100R: the default 37.5 ms interval gives a 58 ms
        median round trip; throughput-optimized parameters give 15 ms and
        30 ms. Elsewhere this is a no-op.
        """
        device = controller.ble_device()
        if device is None or not hasattr(device, "request_preferred_connection_parameters"):
            return
        try:
            from winrt.windows.devices.bluetooth import (
                BluetoothLEPreferredConnectionParameters as Preferred,
            )

            self._param_request = device.request_preferred_connection_parameters(Preferred.throughput_optimized)
        except Exception as err:  # noqa: BLE001 - tuning is best effort
            logger.info("connection tuning unavailable: %s", err)
            return

        async def read_back() -> None:
            await asyncio.sleep(1.5)
            try:
                self.interval_ms = device.get_connection_parameters().connection_interval * 1.25
            except Exception as err:  # noqa: BLE001
                logger.debug("connection parameters unreadable: %s", err)
            if self._listener is not None:
                self._listener(self.snapshot())

        asyncio.get_running_loop().create_task(read_back())

    def _tap(self, src: int, access_payload: bytes) -> None:
        # Anything decryptable from the mesh proves the link is alive. Each
        # light publishes a Generic OnOff Status every 15 s on its own, so an
        # idle link is verified for free, without spending sequence numbers.
        self.last_rx = time.monotonic()
        if self._on_access is not None:
            self._on_access(src, access_payload)

    async def _keepalive(self, controller: GodoxController) -> None:
        misses = 0
        while True:
            await asyncio.sleep(self.keepalive_interval)
            if time.monotonic() - self.last_tx < self.idle_before_keepalive:
                continue  # busy streaming: writes are succeeding, skip the probe
            if self.last_rx is not None and time.monotonic() - self.last_rx < self.keepalive_interval + 5:
                misses = 0
                continue  # heard from the light recently (heartbeat): no probe needed
            try:
                await self.probe(controller)
                misses = 0
            except StatusTimeout:
                misses += 1
                logger.info("keepalive miss %d", misses)
                if misses >= 3:
                    self.detail = "light stopped answering"
                    self._dropped.set()
                    return
            except Exception as err:  # noqa: BLE001
                logger.info("keepalive failed: %s", err)
                self._dropped.set()
                return
