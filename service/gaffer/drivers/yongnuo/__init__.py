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
import logging
from pathlib import Path
from typing import Any, Callable, Protocol

from ..base import Advert, Driver, DriverContext, LightStatus
from . import protocol
from .protocol import encode_decimal, encode_plain, encode_power

logger = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).resolve().parents[2] / "models" / "yongnuo"


def retry_delay(failures: int) -> float:
    """Seconds to wait before sending to a light again after ``failures`` failed tries in a row.

    Source: the rule the Godox link supervisor already runs, gaffer/link.py ``Link.run``:
    ``min(30.0, 1.0 * 2 ** min(failures, 5))``. Nothing in the Dart code gives a retry
    schedule (its connect failure waits for a tap), so the project's own rule is the authority.
    """
    return min(30.0, 1.0 * 2 ** min(failures, 5))


#: Seconds a connect may take before it counts as a failure. Source: the Godox link opens its
#: BleakClient with ``timeout=20.0`` (gaffer/link.py ``_session``).
CONNECT_TIMEOUT_S = 20.0
#: Seconds a disconnect may take. Source: the Godox link's ``_teardown`` waits 5 s for
#: ``controller.disconnect()`` (gaffer/link.py); its cleanup after a failed connect waits 4 s.
DISCONNECT_TIMEOUT_S = 5.0


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
        connect_timeout: float = CONNECT_TIMEOUT_S,
    ) -> None:
        super().__init__(context)
        self._factory = transport_factory
        self.models = models if models is not None else load_models()
        self._sleep = sleep
        self._connect_timeout = connect_timeout
        self._closing = False
        self._transports: dict[str, Transport] = {}
        self._on: dict[str, bool] = {}
        self._last: dict[str, Any] = {}
        self._held: dict[str, bool] = {}
        self._reachable: dict[str, bool] = {}
        self._pending: dict[str, tuple[Any, Any]] = {}
        #: One sender task, one lock and one "nothing left to try" flag per light, so a light
        #: that is off or held by a phone app never delays another light.
        self._workers: dict[str, asyncio.Task] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._settled: dict[str, asyncio.Event] = {}
        self._backing_off: set[str] = set()
        self._kicks: dict[str, asyncio.Event] = {}
        self._failures: dict[str, int] = {}

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
        try:
            return self.models[light.radio_id]
        except KeyError:
            raise ValueError(f"{light.radio_id} is not a Yongnuo model Gaffer knows.") from None

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
        """Nothing to start: a sender task begins with a light's first ``apply``."""
        self._closing = False

    async def stop(self) -> None:
        """Release every link and forget what was known about each light. Safe to call twice.

        ``_closing`` is set first, so an identify or connect that is mid-flight cannot open a
        link after this returns.
        """
        self._closing = True
        workers = list(self._workers.values())
        self._workers.clear()
        for worker in workers:
            worker.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        for settled in self._settled.values():
            settled.set()
        for address in list(self._transports):
            await self._drop(address)  # one light that will not let go never keeps the rest connected
        for table in (self._pending, self._settled, self._kicks, self._failures, self._on, self._last,
                      self._held, self._reachable):
            table.clear()
        self._backing_off.clear()

    async def connect(self, light: Any) -> None:
        self._channel(light)
        async with self._lock(light.address):
            await self._open(light)

    def apply(self, light: Any, state: Any) -> None:
        """Queue ``state``; the light's sender task sends it. Bad input raises here, before anything is queued.

        New input also ends any back-off at once: the user has just done something, so try now.
        Back-off only spaces out retries that have no new input behind them.
        """
        self._frames(light, state)  # validates the channel and the model now, not in the task
        if self._closing:
            return
        self._queue(light, state, replace=True)
        if light.address in self._backing_off:
            self._kicks[light.address].set()

    def _queue(self, light: Any, state: Any, *, replace: bool) -> None:
        address = light.address
        if replace:
            self._pending[address] = (light, state)
        else:
            self._pending.setdefault(address, (light, state))  # a newer apply already there wins
        self._settled.setdefault(address, asyncio.Event()).clear()
        self._kicks.setdefault(address, asyncio.Event())
        worker = self._workers.get(address)
        if worker is None or worker.done():
            self._workers[address] = asyncio.get_running_loop().create_task(self._run(address))

    async def identify(self, light: Any) -> None:
        """Pulse the brightness (full, low, full), then put the light back as it was.

        The light's lock is held throughout, so no other write interleaves with the pulse. If a
        newer state was applied during the pulse, that state wins and nothing is restored over it.
        A light that was never given a state has nothing to go back to and stays at full.
        """
        self._channel(light)
        self._model(light)
        address = light.address
        async with self._lock(address):
            state = self._last.get(address)
            try:
                kelvin = state.cct.kelvin if state else protocol.DEFAULT_MAX_KELVIN
                power_on = self.encode_power(light, True)
                for step, level in enumerate((100, 10, 100)):
                    frames = [self.encode_level(light, kelvin, level)]
                    if step == 0 and power_on is not None and not self._on.get(address, False):
                        frames.insert(0, power_on)  # a light that is off ignores levels until it is switched on
                    await self._transmit(light, frames)
                    if power_on is not None:
                        self._on[address] = True
                    await self._sleep(0.3)
                if state is None or address in self._pending:
                    return
                await self._transmit(light, self._frames(light, state))
                self._on[address] = bool(state.power)
            except Exception:
                if state is not None and not self._closing:
                    self._queue(light, state, replace=False)  # a pulse that broke off must not leave the light at full
                raise

    def status(self, light: Any) -> LightStatus:
        address = light.address
        reachable = self._reachable.get(address)
        transport = self._transports.get(address)
        if transport is not None and not transport.connected:
            reachable = False
        return {"reachable": reachable, "held": self._held.get(address, False)}

    async def flush(self) -> None:
        """Wait until every light's queued state has been tried (tests and shutdown).

        A light that failed and is waiting to retry counts as tried; flush does not wait out its delay.
        """
        await asyncio.gather(*(settled.wait() for settled in list(self._settled.values())))

    # -- sending --------------------------------------------------------------

    def _lock(self, address: str) -> asyncio.Lock:
        return self._locks.setdefault(address, asyncio.Lock())

    async def _run(self, address: str) -> None:
        """Send this light's wanted state until none is left. Latest state wins."""
        settled = self._settled[address]
        try:
            while address in self._pending:
                failed = False
                async with self._lock(address):
                    # Taken only once the light's lock is ours, so a state applied while an
                    # identify pulse holds the lock is still waiting here when the pulse ends.
                    light, state = self._pending.pop(address)
                    try:
                        frames = self._frames(light, state)
                    except ValueError:
                        logger.warning("a Yongnuo light's state could not be encoded; dropped")  # retrying cannot help
                        continue
                    try:
                        await self._transmit(light, frames)
                    except Exception:  # noqa: BLE001 - _transmit recorded it; keep the state and try again later
                        failed = True
                        self._pending.setdefault(address, (light, state))  # a newer apply is already there and wins
                    else:
                        self._last[address] = state
                        self._on[address] = bool(state.power)
                        self._failures.pop(address, None)
                if failed:
                    self._failures[address] = self._failures.get(address, 0) + 1
                    await self._back_off(address, settled)
        finally:
            settled.set()

    async def _back_off(self, address: str, settled: asyncio.Event) -> None:
        """Wait out the retry delay, or less if the user does something to the light meanwhile."""
        kick = self._kicks[address]
        kick.clear()
        self._backing_off.add(address)
        settled.set()  # tried once; a flush does not wait out the delay
        waits = [asyncio.ensure_future(self._sleep(retry_delay(self._failures[address]))),
                 asyncio.ensure_future(kick.wait())]
        try:
            await asyncio.wait(waits, return_when=asyncio.FIRST_COMPLETED)
        finally:
            self._backing_off.discard(address)
            for wait in waits:
                wait.cancel()
            await asyncio.gather(*waits, return_exceptions=True)
        if address in self._pending:
            settled.clear()

    async def _open(self, light: Any) -> Transport | None:
        """Make sure the light has a live link and return it. The caller holds the light's lock."""
        address = light.address
        if self._closing:
            raise ConnectionAbortedError("The Yongnuo driver has stopped.")
        if self.context.demo:
            self._reachable[address] = True
            return None
        transport = self._transports.get(address)
        if transport is not None:
            if transport.connected:
                return transport
            await self._drop(address)  # release a dead link before making a new one
        transport = self._factory(address)
        try:
            await asyncio.wait_for(transport.connect(), self._connect_timeout)
            if self._closing:  # stop() ran while this connect was in flight
                raise ConnectionAbortedError("The Yongnuo driver has stopped.")
        except BaseException as err:
            await self._release(transport)  # a connect that failed or was cut short can leave a half-open link
            if isinstance(err, Exception) and not self._closing:
                self._held[address] = True  # most likely another app holds the link
                self._reachable[address] = False
                self._tell(light)
            raise
        self._held[address] = False
        self._reachable[address] = True
        self._transports[address] = transport
        self._tell(light)
        return transport

    async def _transmit(self, light: Any, frames: list[bytes]) -> None:
        """Open the link if needed and write ``frames``. The caller holds the light's lock."""
        address = light.address
        transport = await self._open(light)
        if transport is None:  # demo: nothing is written
            return
        try:
            for frame in frames:
                await transport.write(frame)
        except Exception:
            self._reachable[address] = False
            await self._drop(address)  # bleak may still say "connected"; the next send starts a fresh link
            self._tell(light)
            raise

    async def _drop(self, address: str) -> None:
        transport = self._transports.pop(address, None)
        if transport is not None:
            await self._release(transport)

    async def _release(self, transport: Transport) -> None:
        """Disconnect, never raising and never waiting longer than the Godox link does."""
        try:
            await asyncio.wait_for(transport.disconnect(), DISCONNECT_TIMEOUT_S)
        except Exception:  # noqa: BLE001 - the Dart _safeDisconnect does the same: already gone, or never fully up
            logger.warning("a Yongnuo light did not disconnect cleanly")

    def _tell(self, light: Any) -> None:
        if self.context.notify:
            self.context.notify(light.id, dict(self.status(light)))
