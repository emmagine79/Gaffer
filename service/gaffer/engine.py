"""The clock that animates the light.

One runner is active at a time: a software effect, a crossfade, a timeline, or
an external stream (audio or screen sync from the browser). Each tick the runner
produces a full :class:`LightState`; the hub hands it to the pump, which
coalesces and diffs, so the engine can tick faster than Bluetooth without harm.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Callable
from typing import Any

from .adapt import adapt_frame
from .blend import blend
from .catalog import ModelCaps
from .colormath import EASINGS, clamp, ease
from .effects import REGISTRY
from .effects.base import Frame
from .state import Cct, Hsi, LightState, Rgbw, apply_patch

logger = logging.getLogger(__name__)

Runner = Callable[[float], LightState | None]  # None = finished
Apply = Callable[[LightState], None]


def frame_to_state(base: LightState, frame: Frame, caps: ModelCaps) -> LightState:
    """One effect or stream frame as a full state, fitted to what this light can show."""
    frame = adapt_frame(frame, caps)
    update: dict[str, Any] = {"power": True, "brightness": round(clamp(frame.brightness, 0, 100), 1), "mode": frame.mode}
    if frame.mode == "cct":
        update["cct"] = Cct(
            kelvin=int(clamp(frame.kelvin, caps.min_kelvin, caps.max_kelvin)),
            gm=int(clamp(frame.gm, caps.gm_min, caps.gm_max)),
        )
    elif frame.mode == "hsi":
        update["hsi"] = Hsi(hue=frame.hue % 360.0, sat=clamp(frame.sat, 0, 100))
    else:
        r, g, b, w = (int(clamp(v, 0, 1000)) for v in frame.rgbw)
        update["rgbw"] = Rgbw(r=r, g=g, b=b, w=w)
    return base.model_copy(update=update)


class Engine:
    def __init__(
        self,
        caps: ModelCaps,
        *,
        get_state: Callable[[], LightState],
        apply: Apply,
        on_change: Callable[[dict[str, Any]], None],
        fps: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.caps = caps
        self.fps = fps
        self._get_state = get_state
        self._apply = apply
        self._on_change = on_change
        self._clock = clock
        self._runner: Runner | None = None
        self._started = 0.0
        self._restore: LightState | None = None
        self._wake = asyncio.Event()
        self.kind: str | None = None
        self.effect_id: str | None = None
        self.params: dict[str, Any] = {}
        self.label = ""
        self.duration: float | None = None
        self.last_stream_at = 0.0
        self.target: LightState | None = None  # where a running transition is heading

    # -- status ------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        elapsed = self._clock() - self._started if self.kind else 0.0
        return {
            "kind": self.kind,
            "effect": self.effect_id,
            "label": self.label,
            "params": {k: v for k, v in self.params.items() if not k.startswith("_")},
            "elapsed": round(elapsed, 2),
            "duration": self.duration,
        }

    def _changed(self) -> None:
        self._on_change(self.status())

    def _begin(self, kind: str, runner: Runner, label: str, *, restore: bool, duration: float | None = None) -> None:
        if self.kind is None:
            self._restore = self._get_state() if restore else None
        elif not restore:
            self._restore = None
        self.kind = kind
        self.label = label
        self.duration = duration
        self._runner = runner
        self._started = self._clock()
        self._wake.set()
        self._changed()

    # -- controls ------------------------------------------------------------------

    def start_effect(self, effect_id: str, params: dict[str, Any] | None = None) -> None:
        effect = REGISTRY.get(effect_id)
        if effect is None:
            raise KeyError(f"no effect {effect_id!r}")
        self.effect_id = effect_id
        self.params = effect.resolve(params)
        self.params["_trigger"] = 0
        step = effect.factory(random.Random())

        def runner(t: float) -> LightState:
            return frame_to_state(self._get_state(), step(t, self.params), self.caps)

        self._begin("effect", runner, effect.name, restore=True)

    def update_params(self, params: dict[str, Any]) -> None:
        if self.kind != "effect" or self.effect_id is None:
            return
        trigger = self.params.get("_trigger", 0)
        self.params = REGISTRY[self.effect_id].resolve({**self.params, **params})
        self.params["_trigger"] = trigger
        self._changed()

    def trigger(self) -> None:
        if self.kind == "effect":
            self.params["_trigger"] = self.params.get("_trigger", 0) + 1

    def start_transition(self, target: LightState, seconds: float, easing: str = "inout") -> None:
        source = self._get_state()
        seconds = max(0.0, seconds)
        if seconds == 0:
            self.stop(restore=False)
            self._apply(target)
            return
        curve = easing if easing in EASINGS else "inout"

        def runner(t: float) -> LightState | None:
            f = t / seconds
            if f >= 1.0:
                self._apply(target)
                return None
            return blend(source, target, ease(curve, f))

        self.effect_id = None
        self.params = {}
        self._begin("transition", runner, f"Fade {seconds:g}s", restore=False, duration=seconds)
        self.target = target

    def play_timeline(self, timeline: dict[str, Any]) -> None:
        base = self._get_state()
        keys = sorted(timeline.get("keyframes", []), key=lambda k: float(k["t"]))
        if len(keys) < 2:
            raise ValueError("a timeline needs at least two keyframes")
        states = [apply_patch(base, k.get("state", {}), self.caps) for k in keys]
        times = [float(k["t"]) for k in keys]
        eases = [str(k.get("ease", "inout")) for k in keys]
        duration = max(times[-1], 0.05)
        loop = bool(timeline.get("loop", False))

        def runner(t: float) -> LightState | None:
            if loop:
                t %= duration
            elif t >= duration:
                self._apply(states[-1])
                return None
            for i in range(len(times) - 1):
                if times[i] <= t <= times[i + 1]:
                    span = times[i + 1] - times[i]
                    f = 1.0 if span <= 0 else (t - times[i]) / span
                    return blend(states[i], states[i + 1], ease(eases[i + 1], f))
            return states[0] if t < times[0] else states[-1]

        self.effect_id = None
        self.params = {}
        self._begin("timeline", runner, str(timeline.get("name", "Timeline")), restore=False, duration=duration)

    def begin_stream(self, source: str) -> None:
        """Start a stream session; frames arrive through :meth:`push_stream`."""
        self._begin("stream", lambda _t: None, source, restore=True)
        self._runner = None  # streams are pushed, not polled
        self.last_stream_at = self._clock()

    def push_stream(self, frame: Frame, source: str) -> None:
        """A frame from outside (audio or screen sync): applied at once, no ticking."""
        self.last_stream_at = self._clock()
        if self.kind != "stream" or self.label != source:
            self._begin("stream", lambda _t: None, source, restore=True)
            self._runner = None  # streams are pushed, not polled
        self._apply(frame_to_state(self._get_state(), frame, self.caps))

    def stop(self, *, restore: bool = True) -> None:
        if self.kind is None:
            return
        restore_to = self._restore if restore else None
        self.kind = None
        self.target = None
        self.effect_id = None
        self.params = {}
        self.label = ""
        self.duration = None
        self._runner = None
        self._restore = None
        self._changed()
        if restore_to is not None:
            self._apply(restore_to)

    def expire_stream(self, quiet: float = 3.0) -> bool:
        """End a stream session whose source has gone silent; keep the last look."""
        if self.kind == "stream" and self._clock() - self.last_stream_at > quiet:
            self.stop(restore=False)
            return True
        return False

    # -- loop --------------------------------------------------------------------------

    def tick(self) -> None:
        runner = self._runner
        if runner is None:
            return
        try:
            state = runner(self._clock() - self._started)
        except Exception:
            logger.exception("%s %r failed; stopping it", self.kind, self.label)
            self._runner = None
            self.stop(restore=True)
            return
        if state is None:
            if self._runner is runner:
                self._runner = None
                self.stop(restore=False)
            return
        self._apply(state)

    async def run(self) -> None:
        period = 1.0 / self.fps
        while True:
            if self._runner is None:
                self._wake.clear()
                await self._wake.wait()
            started = self._clock()
            self.tick()
            await asyncio.sleep(max(0.0, period - (self._clock() - started)))
