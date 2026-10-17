"""The one place commands leave for the light.

Three jobs, all workarounds for a light that takes fire-and-forget writes:

* **Coalescing.** The control slot holds only the latest desired state. A slider
  dragged at 120 Hz, or an effect rendering at 30 Hz, becomes at most
  ``max_rate`` commands a second, and the newest always wins.
* **Diffing.** Only frames whose bytes differ from what was last sent go out,
  and power only when it changes. Every frame costs a mesh sequence number
  from a finite 24-bit budget, so a repeat is pure waste.
* **Ordering.** Auxiliary jobs (fan, readback, raw frames) run FIFO between
  control sends and are never coalesced away.
* **Fairness.** Every light on the mesh has its own slot, served in turn, so an
  effect streaming to one light cannot starve a fade on another. Diffing is per
  light too: the same look on two lights is two different sends.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from .catalog import ModelCaps
from .frames import mode_frame, power_frame
from .state import LightState

logger = logging.getLogger(__name__)

#: Writes one frame to the mesh, addressed to a light's node (None: the default light).
Sender = Callable[[bytes, int | None], Awaitable[None]]
AuxJob = Callable[[], Awaitable[Any]]


def plan_frames(
    desired: LightState,
    caps: ModelCaps,
    *,
    last_power: bool | None,
    last_mode_frame: bytes | None,
) -> tuple[bytes, ...]:
    """Frames needed to move the light from what was last sent to ``desired``."""
    if not desired.power:
        return () if last_power is False else (power_frame(False),)
    frames: list[bytes] = []
    turning_on = last_power is not True
    if turning_on:
        frames.append(power_frame(True))
    frame = mode_frame(desired, caps)
    if turning_on or frame != last_mode_frame:
        frames.append(frame)
    return tuple(frames)


@dataclass
class PumpStats:
    sent: int = 0
    coalesced: int = 0
    skipped_identical: int = 0
    errors: int = 0
    _window: deque[float] = field(default_factory=lambda: deque(maxlen=256))

    def record_send(self, now: float) -> None:
        self.sent += 1
        self._window.append(now)

    def rate(self, now: float, horizon: float = 2.0) -> float:
        recent = [t for t in self._window if now - t <= horizon]
        return len(recent) / horizon

    def to_dict(self, now: float) -> dict[str, float | int]:
        return {
            "sent": self.sent,
            "coalesced": self.coalesced,
            "skipped_identical": self.skipped_identical,
            "errors": self.errors,
            "rate": round(self.rate(now), 1),
        }


class CommandPump:
    def __init__(
        self,
        caps: ModelCaps,
        *,
        max_rate: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
        on_send_failure: Callable[[Exception], None] | None = None,
    ) -> None:
        self.caps = caps
        self.max_rate = max_rate
        self._clock = clock
        self._on_send_failure = on_send_failure
        #: Pending state per light, in the order lights are next served.
        self._desired: dict[int | None, tuple[LightState, ModelCaps]] = {}
        self._aux: deque[tuple[AuxJob, asyncio.Future[Any]]] = deque()
        self._wake = asyncio.Event()
        self._sender: Sender | None = None
        self._last_power: dict[int | None, bool] = {}
        self._last_mode_frame: dict[int | None, bytes] = {}
        self._last_send_at = float("-inf")
        self._generation = 0  # bumped on every attach; stale sends are ignored
        self.stats = PumpStats()

    # -- inputs -------------------------------------------------------------

    def submit(self, desired: LightState, node: int | None = None, caps: ModelCaps | None = None) -> None:
        """Make ``desired`` the state to reach next on ``node``; replaces anything pending for it."""
        if node in self._desired:
            self.stats.coalesced += 1
            del self._desired[node]  # newest wins, and goes to the back of the queue
        self._desired[node] = (desired, caps or self.caps)
        self._wake.set()

    def submit_aux(self, job: AuxJob) -> asyncio.Future[Any]:
        """Queue a one-off job; the returned future resolves with its result."""
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._aux.append((job, future))
        self._wake.set()
        return future

    def attach(self, sender: Sender | None) -> None:
        """Point the pump at a live link, or detach it with ``None``.

        Attaching forgets what was last sent: after a reconnect the light's
        state is unknown, so the next control send re-asserts power and mode.
        """
        self._sender = sender
        self._generation += 1
        self._last_power.clear()
        self._last_mode_frame.clear()
        if sender is not None:
            self._wake.set()

    def forget(self, node: int | None = None, *, everything: bool = False) -> None:
        """A light changed without us (adopted from readback): resend everything to it next time."""
        if everything:
            self._last_power.clear()
            self._last_mode_frame.clear()
            return
        self._last_power.pop(node, None)
        self._last_mode_frame.pop(node, None)

    def reset(self) -> None:
        """Forget every pending write and job: the link they were for is gone.

        Node addresses repeat across networks, so a frame queued for node 2 on
        one network must never reach node 2 on the next.
        """
        self._desired.clear()
        self.forget(everything=True)
        while self._aux:
            _job, future = self._aux.popleft()
            if not future.done():
                future.set_exception(ConnectionResetError("the link moved to another network"))

    def drop(self, node: int | None) -> None:
        """Forget a light entirely: nothing pending, nothing remembered."""
        self._desired.pop(node, None)
        self.forget(node)

    @property
    def attached(self) -> bool:
        return self._sender is not None

    # -- loop ----------------------------------------------------------------

    async def run(self) -> None:
        while True:
            await self._wake.wait()
            self._wake.clear()
            while self._sender is not None and (self._aux or self._desired):
                await self._throttle()
                if self._aux:
                    await self._run_aux()
                elif self._desired:
                    await self._send_control()

    async def _throttle(self) -> None:
        gap = 1.0 / self.max_rate - (self._clock() - self._last_send_at)
        if gap > 0:
            await asyncio.sleep(gap)

    async def _run_aux(self) -> None:
        job, future = self._aux.popleft()
        if future.done():
            return  # its caller gave up (timed out); running it late would surprise them
        try:
            result = await job()
        except Exception as err:  # noqa: BLE001 - reported to whoever queued it
            self.stats.errors += 1
            if not future.done():
                future.set_exception(err)
            # A light that did not answer is normal; a write that failed is link trouble,
            # and after it the sequence number may already be spent.
            if not isinstance(err, TimeoutError) and self._on_send_failure is not None:
                self._on_send_failure(err)
        else:
            if not future.done():
                future.set_result(result)
        self._last_send_at = self._clock()

    async def _send_control(self) -> None:
        node = next(iter(self._desired))
        desired, caps = self._desired.pop(node)
        assert self._sender is not None
        try:
            frames = plan_frames(
                desired,
                caps,
                last_power=self._last_power.get(node),
                last_mode_frame=self._last_mode_frame.get(node),
            )
        except Exception:
            # A state that cannot be encoded must not kill the only exit to the light.
            self.stats.errors += 1
            logger.exception("could not encode state for node %s; dropped", node)
            return
        if not frames:
            self.stats.skipped_identical += 1
            return
        generation = self._generation
        sender = self._sender
        for frame in frames:
            try:
                await sender(frame, node)
            except Exception as err:  # noqa: BLE001 - any write failure means link trouble
                if generation != self._generation:
                    return  # the link this write belonged to is already gone
                # Hold the state for the next link and detach: retrying on a
                # dead link would spin, and the link manager owns recovery.
                self.stats.errors += 1
                self._desired.setdefault(node, (desired, caps))
                self.attach(None)
                logger.warning("send failed (%s); detached until the link recovers", err)
                if self._on_send_failure is not None:
                    self._on_send_failure(err)
                return
            if generation != self._generation:
                return  # re-attached mid-send: the new link re-asserts state itself
            now = self._clock()
            self._last_send_at = now
            self.stats.record_send(now)
        self._last_power[node] = desired.power
        if desired.power:
            self._last_mode_frame[node] = frames[-1]
