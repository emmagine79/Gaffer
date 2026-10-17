"""A studio with no hardware: saved lights of every kind, and a light waiting to be paired.

``python -m gaffer --demo`` runs against this, so the whole app can be tried, developed
and photographed without a Godox light in the room. The lights are real
catalogue models, so every tab adapts exactly as it would for real ones.
"""

from __future__ import annotations

import asyncio
import dataclasses
import time
from collections.abc import Callable
from typing import Any

from .discovery import Nearby
from .lights import LightLibrary
from .link import SequenceVault
from .pairing import Paired, Step

#: Scales every simulated delay; tests set it near zero.
PACE = 1.0

#: (name, radio id, Bluetooth address, x, y) for the seeded lights.
DEMO_LIGHTS: tuple[tuple[str, str, str, float, float], ...] = (
    ("Key light", "008F", "DE:MO:00:00:00:01", 0.30, 0.34),   # ML100R: RGB + white, tint, fan
    ("Fill", "003A", "DE:MO:00:00:00:02", 0.72, 0.36),        # SL60IIBi: bi-colour
    ("Backlight", "000E", "DE:MO:00:00:00:03", 0.50, 0.12),   # SL100D: fixed daylight
    ("Hair light", "0078", "DE:MO:00:00:00:04", 0.20, 0.70),  # MS60R: RGB, battery, native gels
)
#: What a scan finds: a factory-fresh tube light, and a light on someone else's mesh.
DEMO_NEARBY: tuple[Nearby, ...] = (
    Nearby("DE:MO:00:00:00:10", "GD_LED", -58, "unpaired", "0001"),   # TL60
    Nearby("DE:MO:00:00:00:11", "GD_LED", -81, "mesh", "0066", "0000000000000000"),  # ML100Bi, elsewhere
)


def seed(library: LightLibrary) -> None:
    """Fill an empty demo library with one network and the demo lights."""
    if library.lights:
        return
    network = library.create_network()
    for i, (name, radio_id, address, x, y) in enumerate(DEMO_LIGHTS):
        light = library.add_paired(
            network_id=network, address=address, radio_id=radio_id, node_address=2 + 2 * i,
            num_elements=2, device_key="00" * 16, name=name,
        )
        library.save_light(dataclasses.replace(light, x=x, y=y))
    library.set_active(library.lights[0].id)


class DemoScanner:
    """Finds the demo's nearby lights, at a believable pace."""

    def __init__(self) -> None:
        self.devices: dict[str, Any] = {}
        self.busy = False

    async def scan(self, seconds: float, on_found: Callable[[Nearby], None] | None = None) -> list[Nearby]:
        self.busy = True
        try:
            found = []
            for nearby in DEMO_NEARBY:
                await asyncio.sleep(min(0.8, seconds / 4) * PACE)
                seen = Nearby(nearby.address, nearby.name, nearby.rssi, nearby.state, nearby.radio_id,
                              nearby.network_id, time.time())
                found.append(seen)
                if on_found is not None:
                    on_found(seen)
            await asyncio.sleep(max(0.0, seconds - 0.8 * len(DEMO_NEARBY)) * 0.25 * PACE)
            return found
        finally:
            self.busy = False


async def demo_pair(target: Any, *, address: str, vault: SequenceVault, node_address: int,
                    on_step: Step) -> Paired:
    """What pairing looks like, without a light: the same steps, believable timing."""
    for step, seconds in (("provisioning", 1.6), ("binding", 1.1)):
        on_step(step)
        await asyncio.sleep(seconds * PACE)
    on_step("bound")
    return Paired(device_key="00" * 16, num_elements=2)
