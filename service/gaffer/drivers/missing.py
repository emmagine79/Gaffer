"""A stand-in for a driver that is not installed, so a light that names one fails plainly.

A model file can name any driver. If that driver's folder is not there, its lights show as
unreachable and take no commands. Nothing is sent to them through another brand's driver.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import Advert, Driver, LightStatus

if TYPE_CHECKING:  # pragma: no cover
    from ..lights import SavedLight
    from ..state import LightState


class MissingDriver(Driver):
    def __init__(self, driver_id: str) -> None:
        super().__init__()
        self.id = driver_id

    def match(self, advert: Advert) -> str | None:
        return None

    async def connect(self, light: SavedLight) -> None:
        raise ConnectionError(f"the {self.id} driver is not installed")

    def apply(self, light: SavedLight, state: LightState) -> None:
        return None

    async def identify(self, light: SavedLight) -> None:
        return None

    def status(self, light: SavedLight) -> LightStatus:
        return {"reachable": False, "held": False}
