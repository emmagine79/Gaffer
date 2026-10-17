"""The demo stand-in driver: takes commands and sends them nowhere.

Demo mode seeds a Zhiyun and a Yongnuo light before those brands' drivers exist, and
a demo must never open Bluetooth anyway. Their stand-in models name this driver, so
a real driver never sees a demo light.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from .base import Advert, Driver, LightStatus

if TYPE_CHECKING:  # pragma: no cover
    from ..lights import SavedLight
    from ..state import LightState


class DemoDriver(Driver):
    id = "demo"

    def __init__(self, context=None) -> None:  # noqa: ANN001 - same signature as Driver
        super().__init__(context)
        #: The last state each light was told to take: what a real driver would have written.
        self.applied: dict[str, LightState] = {}
        self._connected: dict[str, float] = {}

    def match(self, advert: Advert) -> str | None:
        return None

    async def connect(self, light: SavedLight) -> None:
        self._connected[light.id] = time.monotonic()

    def apply(self, light: SavedLight, state: LightState) -> None:
        self.applied[light.id] = state

    async def identify(self, light: SavedLight) -> None:
        await asyncio.sleep(0)

    def status(self, light: SavedLight) -> LightStatus:
        return {"reachable": True if light.id in self._connected else None, "held": False}
