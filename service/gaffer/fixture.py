"""One light as the studio runs it: what it is, how it looks, and what animates it."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, NamedTuple

from .adapt import adapt_state
from .catalog import ModelCaps, model_caps
from .drivers.base import Driver
from .engine import Engine
from .lights import SavedLight
from .state import LightState
from .sync import SyncTracker


class BeforeMax(NamedTuple):
    """What a light had before Gaffer saw Max Mode come on, and whether its colour temperature was set since."""

    brightness: float
    kelvin: int
    kelvin_changed: bool = False


EngineApply = Callable[["Fixture", LightState], None]
EngineChanged = Callable[["Fixture", dict[str, Any]], None]


class Fixture:
    def __init__(
        self,
        light: SavedLight,
        state: LightState,
        *,
        on_engine_state: EngineApply,
        on_engine_change: EngineChanged,
        driver_for: Callable[[ModelCaps], Driver],
        fps: float = 60.0,
    ) -> None:
        self.light = light
        self._driver_for = driver_for
        self.caps: ModelCaps = model_caps(light.radio_id)
        self.state = adapt_state(state, self.caps)
        self.state_source = "restored"
        self.dirty = False
        self.engine = Engine(
            self.caps,
            get_state=lambda: self.state,
            apply=lambda s: on_engine_state(self, s),
            on_change=lambda status: on_engine_change(self, status),
            fps=fps,
        )
        self.sync = SyncTracker()
        self.readback: dict[str, Any] = {"cct": None, "hsi": None, "heartbeat_at": None, "latency_ms": None}
        self.device: dict[str, Any] = {"fan": None, "battery": None, "smoothness": None, "control": None}
        self.last_control_at = 0.0
        self.adopting = True  # first contact this run: read the light before writing it
        self.request_at: dict[int, float] = {}
        self.stream_source: str | None = None
        #: Brightness and kelvin the light had before Gaffer saw Max Mode come on. Max off in Gaffer puts the
        #: brightness back, and the kelvin unless one was set while Max Mode was on.
        self.before_max: BeforeMax | None = None
        self.own_values = False  # a look's fade is running: group mirroring leaves this light alone (looks.py)

    @property
    def id(self) -> str:
        return self.light.id

    @property
    def node(self) -> int:
        return self.light.node_address

    @property
    def driver(self) -> Driver:
        """The driver that commands this light: whichever the light's model names."""
        return self._driver_for(self.caps)

    @property
    def reachable(self) -> bool | None:
        """True when heard from lately, False when silent, None before the first word."""
        return self.driver.status(self.light)["reachable"]

    @property
    def held(self) -> bool:
        """True when another controller (a phone app) holds this light's one connection."""
        return bool(self.driver.status(self.light)["held"])

    @property
    def max_mode(self) -> bool | None:
        """Max Mode (turbo) as the driver last set it. None for a model without the switch."""
        return self.driver.max_mode(self.light) if self.caps.max_mode else None

    def use_caps(self, caps: ModelCaps) -> None:
        """The model changed (recognised or picked): refit everything to it."""
        self.caps = caps
        self.engine.caps = caps
        self.state = adapt_state(self.state, caps)
        self.dirty = True

    def view(self) -> dict[str, Any]:
        """The light as the browser sees it: identity, abilities, state."""
        return {
            **self.light.public(),
            "caps": self.caps.to_dict(),
            "gel_key": gel_key(self.caps),
            "state": self.state.model_dump(),
            "source": self.state_source,
            "engine": self.engine.status(),
            "readback": self.readback,
            "device": self.device,
            "reachable": self.reachable,
            "held": self.held,
            "max_mode": self.max_mode,
        }


def gel_key(caps: ModelCaps) -> str | None:
    """Which gel table a light uses; lights that share one share the key."""
    support = caps.gel_support
    if support is None:
        return None
    if support == "native":
        return f"native:{caps.color_chip_version}"
    if support == "emulated":
        return "emulated"
    tint = "tint" if caps.has_tint else "plain"
    return f"white:{tint}:{caps.min_kelvin}-{caps.max_kelvin}"
