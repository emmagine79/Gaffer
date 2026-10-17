"""The driver contract: what every light brand implements to plug into Gaffer.

One ``Driver`` per brand (Godox, Zhiyun, Yongnuo). The hub never talks to a
brand's Bluetooth link directly; it asks the fixture's driver.

Rules every driver follows
--------------------------
* ``apply`` is synchronous and never blocks. It records the wanted state and
  returns; the driver sends bytes in its own task, latest state wins. The hub
  calls it up to 60 times a second while a fader moves or an effect runs.
* ``encode_*`` functions are pure: same arguments, same bytes, no I/O, no
  clock. Byte tests call them directly. They live beside the driver (in its
  package) and the driver's ``apply`` calls them.
* ``match`` is pure and cheap. It looks at one advertisement and returns the
  model id (the key of the model file or table row) or ``None``. It never
  raises on odd input.
* Errors a driver raises or reports carry a plain-words message and a code,
  never a file path.

Registry: ``gaffer.drivers`` imports every sub-package of ``gaffer/drivers/``
and registers each concrete ``Driver`` subclass it finds. A new brand is a new
folder; nothing else changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids an import cycle
    from ..lights import SavedLight
    from ..state import LightState


@dataclass(frozen=True, slots=True)
class Advert:
    """One Bluetooth advertisement, reduced to what a driver may match on."""

    address: str
    name: str | None = None
    rssi: int | None = None
    #: Advertised service UUIDs, lower case, full 128-bit form.
    services: tuple[str, ...] = ()
    #: Manufacturer data by company id.
    manufacturer_data: dict[int, bytes] = field(default_factory=dict)


class LightStatus(TypedDict):
    """What ``Driver.status`` returns."""

    #: True when the light answered lately, False when silent, None before first contact.
    reachable: bool | None
    #: True when another controller (a phone app) holds the light's one connection.
    held: bool


@dataclass(slots=True)
class DriverContext:
    """What the hub hands a driver when it builds one."""

    #: Gaffer's data folder (``~/Library/Application Support/Gaffer``), or None in tests.
    data_dir: Path | None = None
    #: True for ``--demo``: a driver must not open Bluetooth.
    demo: bool = False
    #: ``notify(light_id, {"reachable": ..., "held": ...})`` when a driver learns something.
    notify: Callable[[str, dict[str, Any]], None] | None = None


class Driver(ABC):
    """One brand's way of finding, connecting to and commanding its lights."""

    #: Stable brand key. Matches the ``driver`` field of the model files.
    id: str = ""

    def __init__(self, context: DriverContext | None = None) -> None:
        self.context = context or DriverContext()

    @abstractmethod
    def match(self, advert: Advert) -> str | None:
        """The model id this advertisement is, or None when it is not this brand's."""

    async def start(self) -> None:
        """Begin background work (a link, a pump). Called once when the hub starts."""

    async def stop(self) -> None:
        """Release Bluetooth and end background work. Safe to call twice."""

    @abstractmethod
    async def connect(self, light: SavedLight) -> None:
        """Open a link to the light. Returns when it can take commands."""

    @abstractmethod
    def apply(self, light: SavedLight, state: LightState) -> None:
        """Make the light match ``state``. Synchronous, non-blocking, latest wins."""

    @abstractmethod
    async def identify(self, light: SavedLight) -> None:
        """Make the light show which one it is (a brightness pulse), then restore it."""

    @abstractmethod
    def status(self, light: SavedLight) -> LightStatus:
        """``{"reachable": bool | None, "held": bool}`` for this light."""

    def needs_channel(self, caps: Any) -> bool:
        """True when a light of this model must be told a radio channel when it is added (Yongnuo).

        ``caps`` is the model's ``ModelCaps``. The default is no: most lights have no such setting."""
        return False

    def check_channel(self, channel: Any) -> int:
        """The channel as the driver will send it, or ``ValueError`` in plain words. Only called for a
        model whose ``needs_channel`` is True."""
        raise ValueError("This light has no channel setting.")

    async def forget_light(self, light_id: str) -> None:
        """Let go of this light: the hub no longer has it with this driver (forgotten, paired again,
        or given another brand's model). Close any link you hold for it, stop any task that writes to
        it, and drop whatever is kept for it (queued writes, last-heard time). When this returns, this
        driver must send the light nothing more: the hub awaits it before the light's new driver
        connects, so two drivers never drive one light. The id can come back later, so a stale entry
        would be read as the new light's. Default: nothing kept."""
