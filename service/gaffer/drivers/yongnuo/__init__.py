"""The Yongnuo driver: BLE lights on the TI UART service, one write characteristic.

Implements ``gaffer.drivers.base.Driver``: ``match`` is pure, ``apply`` is synchronous
and non-blocking (latest state wins, a task sends it), the rest are async as the contract
says; the ``encode_*`` functions are pure and live in ``protocol.py``. Which frame a light takes, its power frames and its Kelvin range all come
from its model file under ``gaffer/models/yongnuo/``. Each light stores its own channel.

The driver never opens Bluetooth itself: it writes through a transport, so tests give it
one that only records bytes.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Callable, Protocol

from ..base import Advert, Driver, DriverContext, LightStatus
from . import protocol
from .protocol import encode_decimal, encode_plain, encode_power

MODELS_DIR = Path(__file__).resolve().parents[2] / "models" / "yongnuo"


class Transport(Protocol):
    async def connect(self) -> None: ...
    async def write(self, data: bytes) -> None: ...
    async def disconnect(self) -> None: ...
    @property
    def connected(self) -> bool: ...


class BleakTransport:
    """Writes to the Yongnuo write characteristic over bleak. Needs a real light."""

    def __init__(self, address: str) -> None:
        self._address = address
        self._client: Any = None

    async def connect(self) -> None:
        from bleak import BleakClient

        client = BleakClient(self._address)
        await client.connect()
        self._client = client

    async def write(self, data: bytes) -> None:
        await self._client.write_gatt_char(protocol.WRITE_UUID, data, response=False)

    async def disconnect(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            await client.disconnect()

    @property
    def connected(self) -> bool:
        return bool(self._client and self._client.is_connected)


def load_models(directory: Path = MODELS_DIR) -> dict[str, dict[str, Any]]:
    models: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.glob("*.json")):
        row = json.loads(path.read_text(encoding="utf-8"))
        models[row["id"]] = row
    return models


class YongnuoDriver(Driver):
    id = "yongnuo"

    def __init__(
        self,
        context: DriverContext | None = None,
        *,
        transport_factory: Callable[[str], Transport] = BleakTransport,
        models: dict[str, dict[str, Any]] | None = None,
        sleep: Callable[[float], Any] = asyncio.sleep,
    ) -> None:
        super().__init__(context)
        self._factory = transport_factory
        self.models = models if models is not None else load_models()
        self._sleep = sleep
        self._transports: dict[str, Transport] = {}
        self._on: dict[str, bool] = {}
        self._last: dict[str, Any] = {}
        self._held: dict[str, bool] = {}
        self._reachable: dict[str, bool] = {}
        self._pending: dict[str, tuple[Any, Any]] = {}
        self._task: asyncio.Task | None = None
        self._wake = asyncio.Event()
        self._io = asyncio.Lock()

    # -- matching -------------------------------------------------------------

    def match(self, advert: Advert) -> str | None:
        """Model id for an advert, or None. By name: case-insensitive prefix from the model file.

        A real YN150Li advertises service 0xFEFF, not F000AA60, so the service is not required.
        """
        try:
            name = (advert.name or "").lower()
            if not name:
                return None
            best: tuple[int, str] | None = None
            for model_id, row in self.models.items():
                prefix = row["match"]["name_prefix"].lower()
                if name.startswith(prefix) and (best is None or len(prefix) > best[0]):
                    best = (len(prefix), model_id)
            return best[1] if best else None
        except Exception:  # the contract: match never raises on odd input
            return None

    # -- frames ---------------------------------------------------------------

    def _model(self, light: Any) -> dict[str, Any]:
        return self.models[light.radio_id]

    def _channel(self, light: Any) -> int:
        channel = getattr(light, "channel", None)
        if channel is None:
            raise ValueError("Set this Yongnuo light's channel first.")
        return protocol.check_channel(channel)

    def encode_level(self, light: Any, kelvin: float, brightness: float) -> bytes:
        row = self._model(light)
        encoder = encode_decimal if row["driver_data"]["frame_variant"] == "decimal" else encode_plain
        return encoder(self._channel(light), kelvin, brightness, min_kelvin=row["min_kelvin"], max_kelvin=row["max_kelvin"])

    def encode_power(self, light: Any, on: bool) -> bytes | None:
        """The model file's power frame, or None for a model that has none (decimal)."""
        template = self._model(light)["driver_data"].get("power_on" if on else "power_off")
        return encode_power(template, self._channel(light)) if template else None

    def _frames(self, light: Any, state: Any) -> list[bytes]:
        """The frames that take the light to ``state``, given what was last sent to it."""
        kelvin = state.cct.kelvin
        if not state.power:
            off = self.encode_power(light, False)
            return [off if off is not None else self.encode_level(light, kelvin, 0)]
        frames = []
        on = self.encode_power(light, True)
        if on is not None and not self._on.get(light.address, False):
            frames.append(on)
        frames.append(self.encode_level(light, kelvin, state.brightness))
        return frames

    # -- contract -------------------------------------------------------------

    async def start(self) -> None:
        self._ensure_task()

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self._pending.clear()
        for address in list(self._transports):
            await self._drop(address)

    async def connect(self, light: Any) -> None:
        self._channel(light)
        if self.context.demo:
            self._reachable[light.address] = True
            return
        if light.address in self._transports and self._transports[light.address].connected:
            return
        transport = self._factory(light.address)
        try:
            await transport.connect()
        except Exception:
            self._held[light.address] = True  # most likely another app holds the link
            self._reachable[light.address] = False
            self._tell(light)
            raise
        self._held[light.address] = False
        self._reachable[light.address] = True
        self._transports[light.address] = transport
        self._tell(light)

    def apply(self, light: Any, state: Any) -> None:
        """Queue ``state``; a task sends it. Bad input raises here, before anything is queued."""
        self._frames(light, state)  # validates the channel and the model now, not in the task
        self._pending[light.address] = (light, state)
        self._ensure_task()
        self._wake.set()

    async def identify(self, light: Any) -> None:
        """Pulse the brightness (full, low, full), then put the last state back."""
        state = self._last.get(light.address)
        kelvin = state.cct.kelvin if state else protocol.DEFAULT_MAX_KELVIN
        for level in (100, 10, 100):
            await self._send(light, [self.encode_level(light, kelvin, level)])
            await self._sleep(0.3)
        if state is not None:
            await self._send(light, self._frames(light, state), state)

    def status(self, light: Any) -> LightStatus:
        transport = self._transports.get(light.address)
        reachable = transport.connected if transport else self._reachable.get(light.address)
        return {"reachable": reachable, "held": self._held.get(light.address, False)}

    async def flush(self) -> None:
        """Wait until everything queued has been sent (tests and shutdown)."""
        while self._pending or self._io.locked():
            await asyncio.sleep(0)

    # -- sending --------------------------------------------------------------

    def _ensure_task(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self._pump())

    async def _pump(self) -> None:
        while True:
            await self._wake.wait()
            self._wake.clear()
            while self._pending:
                address = next(iter(self._pending))
                light, state = self._pending.pop(address)
                try:
                    await self._send(light, self._frames(light, state), state)
                except Exception:
                    pass  # _send already recorded the failure; the next apply tries again

    async def _send(self, light: Any, frames: list[bytes], state: Any = None) -> None:
        async with self._io:
            try:
                await self.connect(light)
                if not self.context.demo:
                    for frame in frames:
                        await self._transports[light.address].write(frame)
            except Exception:
                self._reachable[light.address] = False
                self._tell(light)
                raise
            if state is not None:
                self._last[light.address] = state
                self._on[light.address] = bool(state.power)

    async def _drop(self, address: str) -> None:
        transport = self._transports.pop(address, None)
        if transport is not None:
            await transport.disconnect()

    def _tell(self, light: Any) -> None:
        if self.context.notify:
            self.context.notify(light.id, dict(self.status(light)))
