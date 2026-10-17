"""The Godox driver: lumen's command pump and controller behind the driver contract.

Godox lights sit on one Bluetooth mesh reached through a single proxy link, so the
driver owns the one shared ``CommandPump`` (coalescing, diffing, fairness) and the
controller the link hands it. The link manager itself stays with the hub, which
builds it from its own callbacks and gives the driver the controller on connect.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from ...catalog import model_caps
from ...discovery import MESH_PROV, MESH_PROXY, radio_id_from_manufacturer
from ...pump import AuxJob, CommandPump, Sender
from ...state import LightState
from ..base import Advert, Driver, DriverContext, LightStatus

if TYPE_CHECKING:  # pragma: no cover
    from ...lights import SavedLight

logger = logging.getLogger(__name__)

#: A light that has said nothing for this long is shown as unreachable. It
#: publishes a heartbeat every 15 s on its own, so two missed beats is telling.
SILENT_AFTER = 40.0
#: Identify: how long each step of the brightness pulse holds, in seconds.
PULSE_SECONDS = 0.45


class GodoxDriver(Driver):
    id = "godox"

    def __init__(self, context: DriverContext | None = None, *, max_rate: float = 30.0,
                 on_send_failure: Callable[[Exception], None] | None = None) -> None:
        super().__init__(context)
        self.pump = CommandPump(model_caps(""), max_rate=max_rate, on_send_failure=on_send_failure)
        self.controller: Any = None
        self._task: asyncio.Task[Any] | None = None
        self._heard: dict[str, float] = {}
        self._applied: dict[str, LightState] = {}

    def configure(self, *, max_rate: float, on_send_failure: Callable[[Exception], None] | None) -> None:
        """Settings the hub knows and the registry does not. Call before ``start``."""
        self.pump = CommandPump(model_caps(""), max_rate=max_rate, on_send_failure=on_send_failure)

    # -- the contract -----------------------------------------------------------------

    def match(self, advert: Advert) -> str | None:
        """The model id in a mesh light's manufacturer data, or None when it is not a Godox light."""
        services = {s.lower() for s in advert.services}
        if MESH_PROV not in services and MESH_PROXY not in services:
            return None
        try:
            return radio_id_from_manufacturer(advert.manufacturer_data)
        except Exception:  # an odd advertisement is not ours, never an error
            return None

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.pump.run())

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def connect(self, light: SavedLight) -> None:
        """Godox lights share one mesh link that the hub's link manager keeps up on its own.

        Connecting is therefore only making sure the pump is running.
        """
        await self.start()

    def apply(self, light: SavedLight, state: LightState) -> None:
        self._applied[light.id] = state
        self.pump.submit(state, light.node_address, model_caps(light.radio_id))

    async def identify(self, light: SavedLight) -> None:
        """Pulse the light bright, dim, bright, dim, then put it back as it was."""
        base = self._applied.get(light.id) or LightState()
        high = base.model_copy(update={"power": True, "brightness": 100.0})
        low = base.model_copy(update={"power": True, "brightness": 10.0})
        try:
            for step in (high, low, high, low):
                self.apply(light, step)
                await asyncio.sleep(PULSE_SECONDS)
        finally:
            self.apply(light, base)

    def status(self, light: SavedLight) -> LightStatus:
        """Reachable once heard from lately. A mesh light is never held by a phone, so ``held`` is False."""
        heard = self._heard.get(light.id)
        reachable = None if heard is None else time.monotonic() - heard < SILENT_AFTER
        return {"reachable": reachable, "held": False}

    # -- what the hub tells the driver --------------------------------------------------

    def mark_heard(self, light_id: str) -> None:
        self._heard[light_id] = time.monotonic()

    def attach_controller(self, controller: Any, after_send: Callable[[bytes, int | None], None]) -> None:
        """The link came up: send queued frames through ``controller``; call ``after_send`` per frame."""
        self.controller = controller

        async def send(frame: bytes, node: int | None) -> None:
            await controller.send_payload(frame, dst=node)
            after_send(frame, node)

        self.attach_sender(send)

    def attach_sender(self, sender: Sender | None) -> None:
        self.pump.attach(sender)

    def detach_controller(self) -> None:
        self.controller = None
        self.pump.attach(None)

    def run_aux(self, job: AuxJob) -> asyncio.Future[Any]:
        """Queue a one-off job (a read, a fan change) in line with the control writes."""
        return self.pump.submit_aux(job)

    def forget(self, node: int | None = None, *, everything: bool = False) -> None:
        """The light changed without us: resend everything to it next time."""
        self.pump.forget(node, everything=everything)

    def drop(self, node: int | None) -> None:
        self.pump.drop(node)

    def reset(self) -> None:
        """Forget every pending write: the link they were for is gone."""
        self.pump.reset()

    def set_max_rate(self, rate: float) -> None:
        self.pump.max_rate = rate

    def stats(self) -> dict[str, float | int]:
        return self.pump.stats.to_dict(time.monotonic())

    def forget_light(self, light_id: str) -> None:
        self._heard.pop(light_id, None)
        self._applied.pop(light_id, None)


__all__ = ["PULSE_SECONDS", "SILENT_AFTER", "GodoxDriver"]
