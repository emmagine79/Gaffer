"""Controllers the studio talks through: the real one, and a simulated light."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

from godox_mesh_bt import GodoxController
from godox_mesh_bt.controller import REQUEST_OPCODE
from godox_mesh_bt.crypto import (
    build_vendor_access_payload,
    decrypt_proxy_network_pdu,
    pack_proxy_network_pdus,
)
from godox_mesh_bt.protocol import build_status_request, build_v2_command

logger = logging.getLogger(__name__)

RESPONSE_OPCODE = 0x0211F1
#: Receives every decrypted message from the mesh: (source node address, access payload).
AccessListener = Callable[[int, bytes], None]
#: Hops a relayed command may take. The gateway light hears the GATT link
#: directly; every other light is reached by the gateway re-broadcasting the
#: command on the mesh, which needs TTL 2 or more. A few spare hops let lights
#: out of the gateway's range relay for each other.
DEFAULT_RELAY_TTL = 5


class StudioController(GodoxController):
    """The library controller, plus a tap on every decrypted inbound message.

    The library only surfaces the status replies it knows how to parse; the
    studio also wants the HSI record and the light's unprompted Generic OnOff
    heartbeat, so the raw access payload is handed to a listener first.
    """

    def __init__(
        self,
        *args: Any,
        on_access: AccessListener | None = None,
        gateway_node: int | None = None,
        relay_ttl: int = DEFAULT_RELAY_TTL,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.on_access = on_access
        #: The node this connection is to. Commands for it go with TTL 0
        #: ("deliver to me, never relay"): measured on an ML100R, that keeps
        #: the light's radio free for the GATT link and the stream steady.
        self.gateway_node = gateway_node
        #: TTL for commands to every other light, which the gateway relays.
        self.relay_ttl = relay_ttl
        self._keys = (bytes.fromhex(self.state.network_key), bytes.fromhex(self.state.app_key))

    def ttl_for(self, destination: int) -> int:
        return 0 if destination == self.gateway_node else max(2, self.relay_ttl)

    async def send_payload(self, payload: bytes, *, dst: int | None = None) -> None:
        """The library's send, with a per-destination TTL and keys decoded once."""
        destination = self.state.node_address if dst is None else dst
        net_key, app_key = self._keys
        # Gel, wide-RGB and most V3 effect frames do not fit one packet; they go
        # as a segmented message, one sequence number per segment.
        proxy_pdus = pack_proxy_network_pdus(
            build_vendor_access_payload(REQUEST_OPCODE, payload),
            net_key,
            app_key,
            iv_index=self.state.iv_index,
            seq=self.state.sequence_number,
            src=self.state.provisioner_address,
            dst=destination,
            ttl=self.ttl_for(destination),
        )
        for proxy_pdu in proxy_pdus:
            await self._client.write_proxy(proxy_pdu)
            self._advance_state()
        self._control_write_pending = True

    def ble_device(self) -> Any:
        """The platform BLE object under bleak, for platform-specific tuning."""
        client = getattr(self._client, "_client", None)
        backend = getattr(client, "_backend", None)
        return getattr(backend, "_requester", None)

    def _handle_response(self, proxy_pdu: bytes) -> None:
        if self.on_access is not None and proxy_pdu and (proxy_pdu[0] & 0x3F) == 0x00:
            try:
                decrypted = decrypt_proxy_network_pdu(
                    proxy_pdu,
                    bytes.fromhex(self.state.network_key),
                    bytes.fromhex(self.state.app_key),
                    iv_index=self.state.iv_index,
                )
            except Exception as err:  # noqa: BLE001 - untrusted radio input
                logger.debug("inbound PDU not for us: %s", err)
            else:
                try:
                    self.on_access(decrypted.src, decrypted.access_payload)
                except Exception:
                    logger.exception("access listener failed")
        super()._handle_response(proxy_pdu)

    async def request_record(self, record: int, dst: int | None = None) -> None:
        """Fire a status request for one record; the reply arrives via ``on_access``."""
        await self.send_payload(build_status_request(record=record), dst=dst)


class _DemoNode:
    """One simulated light's status records, as the real ML100R keeps them."""

    def __init__(self) -> None:
        self.a0 = build_v2_command(0xA0, 0x00, bytes([50, 56, 0xFF, 0x00, 0x00]))
        self.a1 = build_v2_command(0xA1, 0x00, bytes([50, 20, 0, 100, 0xFF]))


class DemoController:
    """A simulated mesh: accepts frames for any light, answers records, publishes heartbeats.

    Used by ``--demo`` so the studio can be developed and shown with no light
    in range. Each node answers ``A0``/``A1`` from the last CCT/HSI frame it
    was sent, the way the real light's cache behaves.
    """

    def __init__(self, on_access: AccessListener | None = None, nodes: Callable[[], list[int]] = lambda: [2]) -> None:
        self.on_access = on_access
        self.sent: list[tuple[int | None, bytes]] = []
        self._nodes: dict[int, _DemoNode] = {}
        self._node_list = nodes
        self.is_connected = True

    def _node(self, address: int | None) -> tuple[int, _DemoNode]:
        if address is None:
            address = (self._node_list() or [2])[0]
        return address, self._nodes.setdefault(address, _DemoNode())

    def _reply(self, src: int, v2: bytes) -> None:
        if self.on_access is not None:
            payload = RESPONSE_OPCODE.to_bytes(3, "little") + v2
            asyncio.get_running_loop().call_later(0.04, self.on_access, src, payload)

    async def send_payload(self, payload: bytes, *, dst: int | None = None) -> None:
        self.sent.append((dst, payload))
        del self.sent[:-500]
        address, node = self._node(dst)
        sub = payload[0]
        # The real light's records are copies of the last command of each kind:
        # CCT  f0 BB KK (gm+50) circle GM tenths crc  ->  a0 BB KK ff 00 GM 00
        # HSI  f1 BB HL HH SS 00 tenths crc           ->  a1 BB HL HH SS ff 00
        if sub == 0xF0 and len(payload) == 8:
            node.a0 = build_v2_command(0xA0, 0x00, bytes([payload[1], payload[2], 0xFF, 0x00, payload[5]]))
        elif sub == 0xF1 and len(payload) == 8:
            node.a1 = build_v2_command(0xA1, 0x00, bytes([payload[1], payload[2], payload[3], payload[4], 0xFF]))
        elif sub == 0xFD:
            record = payload[6]
            if record == 0xA0:
                self._reply(address, node.a0)
            elif record == 0xA1:
                self._reply(address, node.a1)
        await asyncio.sleep(0.002)

    async def request_record(self, record: int, dst: int | None = None) -> None:
        await self.send_payload(build_status_request(record=record), dst=dst)

    async def request_status(self, *, timeout: float = 2.5) -> None:
        await asyncio.sleep(0.03)

    async def request_version(self) -> int:
        return 102

    async def request_mcu_version(self) -> str:
        return "1.10 (demo)"

    async def request_battery(self, *, dst: int | None = None, timeout: float = 3.0) -> Any:
        return DEMO_BATTERY

    async def set_fan_mode(self, mode: int, *, dst: int | None = None) -> None:
        self.sent.append((dst, bytes([0xF5, mode])))

    async def set_smoothness(self, mode: int, *, dst: int | None = None) -> None:
        self.sent.append((dst, bytes([0xFC, 0x04, mode])))

    async def set_control_mode(self, mode: int, frequency: int = 0, *, dst: int | None = None) -> None:
        self.sent.append((dst, bytes([0xFC, 0x01, mode, frequency])))

    async def send_v2_command_raw(self, frame: bytes, dst: int | None = None) -> None:
        await self.send_payload(frame, dst=dst)

    async def disconnect(self) -> None:
        self.is_connected = False

    async def heartbeat(self) -> None:
        while True:
            await asyncio.sleep(15)
            if self.on_access is not None:
                for address in self._node_list():
                    self.on_access(address, bytes([0x82, 0x04, 0x01]))


class _DemoBattery:
    power_percent = 77
    hour = 2
    minute = 10
    state = 0
    option = 0


DEMO_BATTERY = _DemoBattery()


class DemoLink:
    """Stands in for :class:`LinkManager` in demo mode, with a believable connect."""

    def __init__(
        self,
        *,
        gateway: Callable[[], Any],
        nodes: Callable[[], list[int]],
        on_connected: Callable[[Any], None],
        on_disconnected: Callable[[], None],
        listener: Callable[[dict[str, Any]], None],
        on_access: AccessListener,
    ) -> None:
        self._gateway = gateway
        self._on_connected = on_connected
        self._on_disconnected = on_disconnected
        self._listener = listener
        self.controller = DemoController(on_access, nodes)
        self.status = "idle"
        self.detail = ""
        self.connected_since: float | None = None
        self.latency_ms: float | None = 41.0
        self.firmware: dict[str, Any] = {"mesh": 102, "mcu": "1.10 (demo)"}
        self._kick = asyncio.Event()
        self._stop = asyncio.Event()

    def snapshot(self) -> dict[str, Any]:
        light = self._gateway()
        return {
            "status": self.status, "detail": self.detail,
            "address": light.address if light is not None else None,
            "gateway": light.id if light is not None and self.connected_since else None,
            "connected_since": self.connected_since, "latency_ms": self.latency_ms, "rssi": -48,
            "sequence": len(self.controller.sent), "sequence_budget": 0.0, "source": 1, "interval_ms": 15.0,
            "firmware": self.firmware, "demo": True,
        }

    def _set(self, status: str, detail: str = "") -> None:
        self.status, self.detail = status, detail
        self._listener(self.snapshot())

    def note_activity(self) -> None: ...
    def report_trouble(self, err: Exception) -> None: ...
    def check_budget(self) -> None: ...

    def reconnect_now(self) -> None:
        self._kick.set()

    def stop(self) -> None:
        self._stop.set()
        self._kick.set()

    async def run(self) -> None:
        from .demo import PACE

        heartbeat = asyncio.create_task(self.controller.heartbeat())
        try:
            while not self._stop.is_set():
                # Cleared before connecting, never after: a stop or reconnect
                # that lands mid-connect must still be seen.
                self._kick.clear()
                self._set("scanning", "looking for your lights")
                await asyncio.sleep(1.0 * PACE)
                if self._stop.is_set():
                    break
                self._set("connecting", "connecting (RSSI -48 dBm)")
                await asyncio.sleep(0.7 * PACE)
                if self._stop.is_set():
                    break
                self.connected_since = time.time()
                self._set("connected", "demo mesh connected")
                self._on_connected(self.controller)
                await self._kick.wait()
                self._on_disconnected()
                self.connected_since = None
        finally:
            heartbeat.cancel()
            self._set("stopped")
