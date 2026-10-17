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
        #: Lights an official app is pretending to hold, set through ``set_held`` (the demo's ``demo.held`` command).
        self._held: set[str] = set()
        #: Every light identify() ran on, oldest first: what a real driver would have pulsed.
        self.identified: list[str] = []
        #: Lights with Max Mode on (the demo's Zhiyun stand-in). A light's power-off ends it, as on the real light.
        self._max_mode: set[str] = set()

    def match(self, advert: Advert) -> str | None:
        return None

    async def connect(self, light: SavedLight) -> None:
        self._connected[light.id] = time.monotonic()

    def apply(self, light: SavedLight, state: LightState) -> None:
        self.applied[light.id] = state
        if not state.power or state.brightness <= 0:
            self._max_mode.discard(light.id)

    async def identify(self, light: SavedLight) -> None:
        self.identified.append(light.id)
        await asyncio.sleep(0)

    async def set_max_mode(self, light: SavedLight, on: bool) -> None:
        (self._max_mode.add if on else self._max_mode.discard)(light.id)

    def max_mode(self, light: SavedLight) -> bool:
        return light.id in self._max_mode

    def status(self, light: SavedLight) -> LightStatus:
        return {"reachable": True if light.id in self._connected else None, "held": light.id in self._held}

    def set_held(self, light_id: str, held: bool) -> None:
        """Demo only: pretend another app takes the light's one connection, or lets go of it."""
        (self._held.add if held else self._held.discard)(light_id)

    def needs_channel(self, caps) -> bool:  # noqa: ANN001 - same signature as Driver
        """The Yongnuo stand-in asks for a channel, as the real Yongnuo driver does."""
        return bool(caps.driver_data.get("needs_channel"))

    def check_channel(self, channel):  # noqa: ANN001, ANN201
        # 0 to 255: the one-byte channel field of a Yongnuo frame (drivers/yongnuo/protocol.py CHANNEL_MAX).
        if isinstance(channel, bool) or not isinstance(channel, int) or not 0 <= channel <= 255:
            raise ValueError("The channel must be a whole number from 0 to 255.")
        return channel

    async def forget_light(self, light_id: str) -> None:
        self.applied.pop(light_id, None)
        self._connected.pop(light_id, None)
        self._held.discard(light_id)
        self._max_mode.discard(light_id)
