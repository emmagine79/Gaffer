"""ZhiyunDriver: Gaffer's driver for Zhiyun MOLUS, FIVERAY and CINEPEER lights.

Behaviour ported from didim99/HA-Zhiyun-Light zhiyun_ble.py (MIT, licence in
THIRD-PARTY/HA-Zhiyun-Light/LICENSE): the connect handshake, the order power ->
colour temperature -> brightness, and brightness 0 meaning power off.

``apply`` only records the wanted state; one task per light sends the difference
from what was last sent. Latest wins. Only white controls are driven.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from ...state import LightState
from ..base import Advert, Driver, DriverContext, LightStatus
from . import protocol as p
from .models import load_models, resolve_model
from .transport import BleakTransport, Link, LinkError, Transport

log = logging.getLogger("gaffer.drivers.zhiyun")

# Pacing from HA-Zhiyun-Light zhiyun_ble.py (_POWER_SETTLE_DELAY, _INIT_STEP_DELAY).
POWER_SETTLE_SECONDS = 0.1
HANDSHAKE_STEP_SECONDS = 0.1
# Identify pulse: brightness values and the hold time for each. Our choice, in the plan (call 10).
IDENTIFY_LEVELS = (100.0, 15.0, 100.0, 15.0)
IDENTIFY_HOLD_SECONDS = 0.35


class ZhiyunError(Exception):
    """A plain-words error with a code. Never carries a path."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(slots=True)
class _Sent:
    """What the driver last sent; ``None`` means unknown, so the next apply sends it."""

    on: bool | None = None
    kelvin: int | None = None
    brightness: float | None = None


class _Light:
    def __init__(self, light_id: str, address: str, model: dict[str, Any]) -> None:
        self.id = light_id
        self.address = address
        self.model = model
        self.link: Link | None = None
        #: Bumped whenever the link is replaced or dropped; a disconnect callback
        #: from an older link carries an older number and is ignored.
        self.generation = 0
        #: Background closes of replaced links; the next open waits for them.
        self.closers: set[asyncio.Future[None]] = set()
        self.reachable: bool | None = None
        self.wanted: LightState | None = None
        self.sent = _Sent()
        self.sequence = 0
        self.wake = asyncio.Event()
        self.idle = asyncio.Event()
        self.idle.set()
        self.lock = asyncio.Lock()
        self.task: asyncio.Task[None] | None = None
        self.reported: dict[str, Any] = {}

    @property
    def op(self) -> int:
        return self.model["driver_data"]["control_mode"]

    def next_sequence(self) -> int:
        seq, self.sequence = self.sequence, (self.sequence + 1) & 0xFFFF
        return seq


class ZhiyunDriver(Driver):
    id = "zhiyun"

    def __init__(
        self,
        context: DriverContext | None = None,
        *,
        transport: Transport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        super().__init__(context)
        self._transport: Transport = transport or BleakTransport()
        self._sleep = sleep
        self._lights: dict[str, _Light] = {}
        self._closing: set[asyncio.Future[None]] = set()
        self._connecting: set[asyncio.Future[None]] = set()
        self._stopped = False

    # -- contract ------------------------------------------------------------

    def match(self, advert: Advert) -> str | None:
        try:
            row = resolve_model(advert.name)
        except Exception:  # noqa: BLE001 - match never raises on odd input
            return None
        return row["id"] if row else None

    async def start(self) -> None:
        self._stopped = False

    async def stop(self) -> None:
        self._stopped = True
        states = list(self._lights.values())
        tasks = [st.task for st in states if st.task] + list(self._connecting)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for st in states:
            st.idle.set()  # release anyone waiting in flush()
            self._drop_link(st)
        await asyncio.gather(*self._closing, return_exceptions=True)
        self._lights.clear()

    async def connect(self, light: Any) -> None:
        st = self._state_for(light)
        # The connect runs in a task the driver owns, so stop() can end it.
        connecting = asyncio.ensure_future(self._connect(st))
        self._connecting.add(connecting)
        connecting.add_done_callback(self._connecting.discard)
        try:
            await connecting
        except asyncio.CancelledError:
            if self._stopped and asyncio.current_task().cancelling() == 0:
                raise ZhiyunError("stopped", "Gaffer is shutting down.") from None
            raise

    async def _connect(self, st: _Light) -> None:
        async with st.lock:
            if self._stopped:
                raise ZhiyunError("stopped", "Gaffer is shutting down.")
            await self._ensure_link(st)
        if st.task is None or st.task.done():
            st.task = asyncio.create_task(self._worker(st))

    def apply(self, light: Any, state: LightState) -> None:
        if self._stopped:
            return
        st = self._state_for(light)
        st.wanted = state
        st.idle.clear()
        if st.task is None or st.task.done():
            st.task = asyncio.create_task(self._worker(st))
        st.wake.set()

    async def identify(self, light: Any) -> None:
        st = self._state_for(light)
        # With nothing applied yet the light's own state is unknown. The user is looking
        # at it, so assume it was lit: never switch off a light we did not switch on.
        original = st.wanted
        restore = original or LightState(
            power=st.sent.on is not False,
            brightness=st.sent.brightness if st.sent.brightness is not None else 50.0,
        )
        pulse: LightState | None = None
        try:
            for level in IDENTIFY_LEVELS:
                pulse = restore.model_copy(update={"power": True, "brightness": level})
                self.apply(light, pulse)
                await self.flush(light)
                if st.reachable is not True:
                    raise ZhiyunError("unreachable", "The light did not answer.")
                await self._sleep(IDENTIFY_HOLD_SECONDS)
                if st.wanted is not pulse:
                    return  # someone else commanded the light: their state wins
        finally:
            if pulse is not None and st.wanted is pulse:
                if st.reachable is True:
                    self.apply(light, restore)
                    await self.flush(light)
                else:
                    st.wanted = original  # the light is gone: the pulse level was never asked for

    def status(self, light: Any) -> LightStatus:
        st = self._lights.get(light.id)
        # held stays False: bleak gives no reliable signal that a phone app holds the link.
        return {"reachable": st.reachable if st else None, "held": False}

    # -- for callers and tests -------------------------------------------------

    async def flush(self, light: Any) -> None:
        """Wait until everything applied so far has been sent (or has failed)."""
        st = self._lights.get(light.id)
        if st is not None:
            await st.idle.wait()

    # -- internals ---------------------------------------------------------------

    def _state_for(self, light: Any) -> _Light:
        st = self._lights.get(light.id)
        if st is None:
            if self._stopped:
                raise ZhiyunError("stopped", "Gaffer is shutting down.")
            models = load_models()
            row = models.get(str(getattr(light, "radio_id", ""))) or resolve_model(getattr(light, "name", None))
            if row is None:
                raise ZhiyunError("unknown_model", "This is not a Zhiyun model Gaffer knows.")
            st = self._lights[light.id] = _Light(light.id, light.address, row)
        return st

    async def _worker(self, st: _Light) -> None:
        while True:
            await st.wake.wait()
            st.wake.clear()
            want = st.wanted
            try:
                if want is not None:
                    await self._send_state(st, want)
            except (ZhiyunError, LinkError) as err:
                log.warning("zhiyun light %s: %s", st.id, err)
                self._lost(st)
            except Exception:  # noqa: BLE001 - one bad apply never ends the worker
                log.exception("zhiyun light %s: unexpected error", st.id)
                self._lost(st)
            if not st.wake.is_set():
                st.idle.set()

    def _lost(self, st: _Light) -> None:
        was = st.reachable
        st.reachable = False
        st.sent = _Sent()
        self._drop_link(st)
        if was is not False:  # one failure, one notification
            self._notify(st)

    def _drop_link(self, st: _Light) -> None:
        """Forget the current link and close it in the background."""
        st.generation += 1
        link, st.link = st.link, None
        if link is not None:
            closing = asyncio.ensure_future(link.close())
            for pending in (self._closing, st.closers):
                pending.add(closing)
                closing.add_done_callback(pending.discard)

    def _notify(self, st: _Light) -> None:
        if self.context.notify:
            self.context.notify(st.id, {"reachable": st.reachable, "held": False})

    async def _ensure_link(self, st: _Light) -> None:
        if st.link is not None and st.link.connected:
            return
        st.sent = _Sent()
        self._drop_link(st)
        generation = st.generation
        try:
            # The old link must be fully closed first: a late disconnect of the same
            # peripheral can cancel the new connection.
            if st.closers:
                await asyncio.shield(asyncio.gather(*st.closers, return_exceptions=True))
            st.link = await self._transport.open(
                st.address, lambda data: self._on_notify(st, data), lambda: self._on_lost(st, generation)
            )
            await self._handshake(st)
        except BaseException:
            # Any failure, including a cancel, leaves no half-handshaken link to reuse.
            self._lost(st)
            raise
        st.reachable = True
        self._notify(st)

    def _on_lost(self, st: _Light, generation: int) -> None:
        if generation == st.generation:  # a late callback from a replaced link changes nothing
            self._lost(st)

    async def _handshake(self, st: _Light) -> None:
        """Identity and state queries, in the iOS app's order; the light drops commands without them."""
        steps = (
            (p.Command.GET_DEVICE_INFO, b""),
            (p.Command.GET_DEVICE_NAME, b""),
            (p.Command.GET_FIRMWARE, b""),
            (p.Command.READ_DEVICE_STATE, p.encode_query()),
            (p.Command.QUERY_BRIGHTNESS, p.encode_query()),
        )
        for command, payload in steps:
            await self._write(st, command, payload)
            await self._sleep(HANDSHAKE_STEP_SECONDS)

    async def _write(self, st: _Light, command: p.Command, payload: bytes) -> None:
        if st.link is None:
            raise ZhiyunError("not_connected", "The light is not connected.")
        await st.link.write(p.build_packet(command, payload, st.next_sequence()))

    async def _send_state(self, st: _Light, want: LightState) -> None:
        async with st.lock:
            await self._ensure_link(st)
            model, op = st.model, st.op
            if not want.power or want.brightness <= 0:
                await self._write(st, p.Command.POWER_STATE, p.encode_power(False, op))
                st.sent.on = False
                return
            force_brightness = False
            if st.sent.on is not True:
                await self._write(st, p.Command.POWER_STATE, p.encode_power(True, op))
                st.sent.on = True
                force_brightness = True
                await self._sleep(POWER_SETTLE_SECONDS)
            lo, hi = model["min_kelvin"], model["max_kelvin"]
            kelvin = max(lo, min(hi, int(want.cct.kelvin)))
            if st.sent.kelvin != kelvin:
                await self._write(st, p.Command.SET_COLOR_TEMP, p.encode_color_temp(kelvin, op, lo, hi))
                st.sent.kelvin = kelvin
            if force_brightness or st.sent.brightness != want.brightness:
                await self._write(st, p.Command.SET_BRIGHTNESS, p.encode_brightness(want.brightness, op))
                st.sent.brightness = want.brightness

    def _on_notify(self, st: _Light, data: bytes) -> None:
        try:
            resp = p.parse_frame(data)
        except p.ProtocolError as err:
            log.debug("zhiyun light %s: dropping frame: %s", st.id, err)
            return
        decoders = {
            p.Command.SET_BRIGHTNESS: ("brightness", p.decode_brightness_response),
            p.Command.SET_COLOR_TEMP: ("kelvin", p.decode_color_temp_response),
            p.Command.POWER_STATE: ("on", p.decode_power_response),
        }
        if resp.command in decoders:
            key, decode = decoders[resp.command]
            value = decode(resp.payload)
            if value is not None:
                st.reported[key] = value
