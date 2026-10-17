"""The Yongnuo driver: BLE lights on the TI UART service, one write characteristic.

Follows the driver contract in the build plan (call 3): ``id``, ``match``, ``start``,
``stop``, ``connect``, ``apply``, ``identify``, ``status`` and pure ``encode_*``
functions. Which frame a light takes, its power frames and its Kelvin range all come
from its model file under ``gaffer/models/yongnuo/``. Each light stores its own channel.

The driver never opens Bluetooth itself: it writes through a transport, so tests give it
one that only records bytes.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Callable, Protocol

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


class YongnuoDriver:
    id = "yongnuo"

    def __init__(
        self,
        transport_factory: Callable[[str], Transport] = BleakTransport,
        models: dict[str, dict[str, Any]] | None = None,
        sleep: Callable[[float], Any] = asyncio.sleep,
    ) -> None:
        self._factory = transport_factory
        self.models = models if models is not None else load_models()
        self._sleep = sleep
        self._transports: dict[str, Transport] = {}
        self._on: dict[str, bool] = {}
        self._last: dict[str, Any] = {}
        self._held: dict[str, bool] = {}

    # -- matching -------------------------------------------------------------

    def match(self, advert: Any) -> str | None:
        """Model id for an advert, or None. By name: case-insensitive prefix from the model file.

        A real YN150Li advertises service 0xFEFF, not F000AA60, so the service is not required.
        """
        name = (getattr(advert, "local_name", None) or getattr(advert, "name", None) or "").lower()
        if not name:
            return None
        best: tuple[int, str] | None = None
        for model_id, row in self.models.items():
            prefix = row["match"]["name_prefix"].lower()
            if name.startswith(prefix) and (best is None or len(prefix) > best[0]):
                best = (len(prefix), model_id)
        return best[1] if best else None

    # -- frames ---------------------------------------------------------------

    def _model(self, light: Any) -> dict[str, Any]:
        return self.models[light.model_id]

    def encode_level(self, light: Any, kelvin: float, brightness: float) -> bytes:
        row = self._model(light)
        encoder = encode_decimal if row["driver_data"]["frame_variant"] == "decimal" else encode_plain
        return encoder(light.channel, kelvin, brightness, min_kelvin=row["min_kelvin"], max_kelvin=row["max_kelvin"])

    def encode_power(self, light: Any, on: bool) -> bytes | None:
        """The model file's power frame, or None for a model that has none (decimal)."""
        template = self._model(light)["driver_data"].get("power_on" if on else "power_off")
        return encode_power(template, light.channel) if template else None

    # -- contract -------------------------------------------------------------

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        for address in list(self._transports):
            await self._drop(address)

    async def connect(self, light: Any) -> None:
        protocol.check_channel(light.channel)
        if light.address in self._transports and self._transports[light.address].connected:
            return
        transport = self._factory(light.address)
        try:
            await transport.connect()
        except Exception:
            self._held[light.address] = True  # most likely another app holds the link
            raise
        self._held[light.address] = False
        self._transports[light.address] = transport

    async def _drop(self, address: str) -> None:
        transport = self._transports.pop(address, None)
        if transport is not None:
            await transport.disconnect()

    async def _write(self, light: Any, frame: bytes) -> None:
        await self.connect(light)
        await self._transports[light.address].write(frame)

    async def apply(self, light: Any, state: Any) -> None:
        """Send what ``state`` asks for. Decimal lights go dark by brightness 0; plain lights by their power-off frame."""
        self._last[light.address] = state
        kelvin = state.cct.kelvin
        if not state.power:
            off = self.encode_power(light, False)
            await self._write(light, off if off is not None else self.encode_level(light, kelvin, 0))
            self._on[light.address] = False
            return
        on = self.encode_power(light, True)
        if on is not None and not self._on.get(light.address, False):
            await self._write(light, on)
        self._on[light.address] = True
        await self._write(light, self.encode_level(light, kelvin, state.brightness))

    async def identify(self, light: Any) -> None:
        """Pulse the brightness (full, low, full), then put the last state back."""
        state = self._last.get(light.address)
        kelvin = state.cct.kelvin if state else protocol.DEFAULT_MAX_KELVIN
        for level in (100, 10, 100):
            await self._write(light, self.encode_level(light, kelvin, level))
            await self._sleep(0.3)
        if state is not None:
            await self.apply(light, state)

    def status(self, light: Any) -> dict[str, bool]:
        transport = self._transports.get(light.address)
        return {"reachable": bool(transport and transport.connected), "held": self._held.get(light.address, False)}
