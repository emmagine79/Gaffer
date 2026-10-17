"""Every message a browser can send, and what it does.

Each handler validates its input and raises ``CommandError`` with a message fit
to show the user; the WebSocket layer turns that into an ``error`` reply.

Light commands act on the light named by ``light`` in the message, or on the
light this browser is editing when there is none.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

from godox_mesh_bt.protocol import build_status_request, build_v2_command, parse_v2_payload

from .adapt import adapt_state
from .effects.base import Frame
from .fixture import Fixture
from .frames import mode_frame
from .hub import Client, Hub, HubError
from .state import LightState, StateError, apply_patch, merge_patch
from .store import COLLECTIONS
from .sync import RECORD_CCT, RECORD_HSI


class CommandError(ValueError):
    pass


Handler = Callable[[Hub, Client, dict[str, Any]], Awaitable[dict[str, Any] | None]]
HANDLERS: dict[str, Handler] = {}


def command(name: str) -> Callable[[Handler], Handler]:
    def register(fn: Handler) -> Handler:
        HANDLERS[name] = fn
        return fn
    return register


def _fixture(hub: Hub, client: Client, m: dict[str, Any]) -> Fixture:
    light = m.get("light") or client.selected
    try:
        return hub.fixture(str(light) if light else None)
    except HubError as err:
        raise CommandError(str(err)) from err


def _base(fixture: Fixture) -> LightState:
    """What a new change builds on: a fade's destination, not its half-blended middle."""
    engine = fixture.engine
    if engine.kind == "transition" and engine.target is not None:
        return engine.target
    return fixture.state


def _patched(fixture: Fixture, patch: Any) -> LightState:
    if not isinstance(patch, dict):
        raise CommandError("expected an object")
    try:
        new = apply_patch(_base(fixture), patch, fixture.caps)
        mode_frame(new, fixture.caps)  # encodable on the wire, or rejected here rather than in the pump
    except StateError as err:
        raise CommandError(str(err)) from err
    except (ValueError, OverflowError, TypeError) as err:
        raise CommandError(f"the light cannot take that: {err}") from err
    return new


def _fitted(fixture: Fixture, patch: Any) -> LightState:
    """A saved look (scene, recent) fitted to this light, whatever light it was made on."""
    if not isinstance(patch, dict):
        raise CommandError("expected an object")
    try:
        return adapt_state(LightState.model_validate(merge_patch(_base(fixture), patch)), fixture.caps)
    except ValueError as err:
        raise CommandError(f"that look is not readable: {err}") from err


#: Commands that take a light over. Each closes the light's open stream session
#: first, so a music frame still in flight cannot snatch it back afterwards.
TAKEOVERS = frozenset({"set", "power", "engine.start", "engine.stop", "timeline.play", "scene.apply", "look.apply"})


async def dispatch(hub: Hub, client: Client, message: dict[str, Any]) -> dict[str, Any] | None:
    kind = str(message.get("type"))
    handler = HANDLERS.get(kind)
    if handler is None:
        raise CommandError(f"unknown command {message.get('type')!r}")
    if kind in TAKEOVERS:
        _fixture(hub, client, message).stream_source = None
    try:
        return await handler(hub, client, message)
    except HubError as err:
        raise CommandError(str(err)) from err


def _start(hub: Hub, fixture: Fixture, target: LightState, fade: float, easing: str = "inout") -> None:
    if fixture.engine.kind is not None:
        fixture.engine.stop(restore=False)
    if fade > 0:
        fixture.engine.start_transition(target, fade, easing)
    else:
        hub.set_state(fixture, target, "app")


# -- light ---------------------------------------------------------------------------


@command("set")
async def _set(hub: Hub, client: Client, m: dict[str, Any]) -> None:
    fixture = _fixture(hub, client, m)
    _start(hub, fixture, _patched(fixture, m.get("patch")), float(m.get("fade") or 0), str(m.get("easing", "inout")))


@command("look.apply")
async def _look_apply(hub: Hub, client: Client, m: dict[str, Any]) -> None:
    """A look saved on any light (recents, presets), fitted to this one."""
    fixture = _fixture(hub, client, m)
    _start(hub, fixture, _fitted(fixture, m.get("patch")), float(m.get("fade") or 0))


@command("power")
async def _power(hub: Hub, client: Client, m: dict[str, Any]) -> None:
    fixture = _fixture(hub, client, m)
    _start(hub, fixture, _base(fixture).model_copy(update={"power": bool(m.get("on"))}), float(m.get("fade") or 0))


@command("power.all")
async def _power_all(hub: Hub, client: Client, m: dict[str, Any]) -> None:
    await hub.power_all(bool(m.get("on")), float(m.get("fade") or 0))


# -- engine -----------------------------------------------------------------------------


@command("engine.start")
async def _engine_start(hub: Hub, client: Client, m: dict[str, Any]) -> None:
    try:
        _fixture(hub, client, m).engine.start_effect(str(m.get("effect")), m.get("params") or {})
    except KeyError as err:
        raise CommandError(str(err)) from err


@command("engine.params")
async def _engine_params(hub: Hub, client: Client, m: dict[str, Any]) -> None:
    _fixture(hub, client, m).engine.update_params(m.get("params") or {})


@command("engine.trigger")
async def _engine_trigger(hub: Hub, client: Client, m: dict[str, Any]) -> None:
    _fixture(hub, client, m).engine.trigger()


@command("engine.stop")
async def _engine_stop(hub: Hub, client: Client, m: dict[str, Any]) -> None:
    _fixture(hub, client, m).engine.stop(restore=bool(m.get("restore", True)))


@command("timeline.play")
async def _timeline_play(hub: Hub, client: Client, m: dict[str, Any]) -> None:
    try:
        _fixture(hub, client, m).engine.play_timeline(m.get("timeline") or {})
    except (ValueError, StateError) as err:
        raise CommandError(str(err)) from err


@command("stream.begin")
async def _stream_begin(hub: Hub, client: Client, m: dict[str, Any]) -> None:
    """Open a stream session: frames from this source may drive the light until it ends."""
    fixture = _fixture(hub, client, m)
    source = str(m.get("source", "stream"))
    fixture.stream_source = source
    fixture.engine.begin_stream(source)


@command("stream.end")
async def _stream_end(hub: Hub, client: Client, m: dict[str, Any]) -> None:
    """Close the session, keeping the last look. A session already taken over is left alone."""
    fixture = _fixture(hub, client, m)
    if fixture.stream_source == str(m.get("source", "stream")):
        fixture.stream_source = None
        if fixture.engine.kind == "stream":
            fixture.engine.stop(restore=False)


@command("stream")
async def _stream(hub: Hub, client: Client, m: dict[str, Any]) -> None:
    fixture = _fixture(hub, client, m)
    if fixture.stream_source is None or str(m.get("source", "stream")) != fixture.stream_source:
        return  # no open session for this source: a late frame after a takeover or an end
    f = m.get("frame") or {}
    mode = f.get("mode", "hsi")
    if mode not in ("hsi", "cct", "rgbw"):
        raise CommandError("stream frames are hsi, cct or rgbw")
    frame = Frame(
        mode=mode,
        brightness=float(f.get("brightness", 50)),
        kelvin=int(f.get("kelvin", 5600)),
        gm=int(f.get("gm", 0)),
        hue=float(f.get("hue", 0)),
        sat=float(f.get("sat", 100)),
        rgbw=tuple(int(v) for v in f.get("rgbw", (0, 0, 0, 0)))[:4],  # type: ignore[arg-type]
    )
    fixture.engine.push_stream(frame, str(m.get("source", "stream")))


# -- device --------------------------------------------------------------------------------


def _need_controller(hub: Hub, fixture: Fixture | None = None) -> Any:
    if hub.controller is None:
        raise CommandError("the lights are not connected")
    if fixture is not None and not hub.on_mesh(fixture):
        raise CommandError(f"{fixture.light.name} is on another network; select it to connect")
    return hub.controller


async def _aux(hub: Hub, job: Callable[[], Awaitable[Any]], timeout: float = 5) -> Any:
    return await asyncio.wait_for(hub.godox.run_aux(job), timeout)


@command("fan")
async def _fan(hub: Hub, client: Client, m: dict[str, Any]) -> None:
    fixture = _fixture(hub, client, m)
    mode = int(m.get("mode", -1))
    if mode not in {f["code"] for f in fixture.caps.fan_modes}:
        raise CommandError(f"{fixture.caps.name} has no fan mode {mode}")
    controller = _need_controller(hub, fixture)
    await _aux(hub, lambda: controller.set_fan_mode(mode, dst=fixture.node))
    fixture.device["fan"] = mode
    hub._broadcast({"type": "device", "light": fixture.id, "device": fixture.device})


@command("device.smoothness")
async def _smoothness(hub: Hub, client: Client, m: dict[str, Any]) -> None:
    fixture = _fixture(hub, client, m)
    mode = int(m.get("mode", -1))
    if mode not in {o["code"] for o in fixture.caps.smoothness_modes}:
        raise CommandError(f"{fixture.caps.name} has no dimming mode {mode}")
    controller = _need_controller(hub, fixture)
    await _aux(hub, lambda: controller.set_smoothness(mode, dst=fixture.node))
    fixture.device["smoothness"] = mode
    hub._broadcast({"type": "device", "light": fixture.id, "device": fixture.device})


@command("device.control")
async def _control(hub: Hub, client: Client, m: dict[str, Any]) -> None:
    fixture = _fixture(hub, client, m)
    mode = int(m.get("mode", -1))
    frequency = int(m.get("frequency", 0))
    if mode not in {o["code"] for o in fixture.caps.control_modes}:
        raise CommandError(f"{fixture.caps.name} has no output mode {mode}")
    if fixture.caps.frequencies and frequency not in {o["code"] for o in fixture.caps.frequencies}:
        raise CommandError(f"{fixture.caps.name} has no frequency setting {frequency}")
    controller = _need_controller(hub, fixture)
    await _aux(hub, lambda: controller.set_control_mode(mode, frequency, dst=fixture.node))
    fixture.device["control"] = {"mode": mode, "frequency": frequency}
    hub._broadcast({"type": "device", "light": fixture.id, "device": fixture.device})


@command("readback")
async def _readback(hub: Hub, client: Client, m: dict[str, Any]) -> None:
    fixture = _fixture(hub, client, m)
    _need_controller(hub, fixture)
    for record in (RECORD_CCT, RECORD_HSI) if fixture.caps.has_colour else (RECORD_CCT,):
        await hub._request(fixture, record)


@command("raw")
async def _raw(hub: Hub, client: Client, m: dict[str, Any]) -> dict[str, Any]:
    fixture = _fixture(hub, client, m)
    text = str(m.get("hex", "")).replace(" ", "").replace(":", "")
    try:
        frame = bytes.fromhex(text)
    except ValueError as err:
        raise CommandError("not valid hex") from err
    if not 2 <= len(frame) <= 20:
        raise CommandError("frames are 2-20 bytes")
    if len(frame) == 8:
        try:
            parse_v2_payload(frame)
        except ValueError as err:
            raise CommandError(f"V2 frame rejected: {err}") from err
    controller = _need_controller(hub, fixture)
    await _aux(hub, lambda: controller.send_payload(frame, dst=fixture.node))
    hub._log("tx", f"{fixture.light.name}: raw {frame.hex(' ')}")
    return {"type": "ack", "of": "raw", "hex": frame.hex()}


@command("lab.frame")
async def _lab_frame(hub: Hub, client: Client, m: dict[str, Any]) -> dict[str, Any]:
    """Build a V2 frame (the server computes the CRC) and send it."""
    fixture = _fixture(hub, client, m)
    try:
        sub = int(m.get("sub", 0)) & 0xFF
        end = int(m.get("end", 0xFF)) & 0xFF
        data = bytes(int(b) & 0xFF for b in (m.get("data") or [])[:5])
    except (TypeError, ValueError) as err:
        raise CommandError("bytes must be numbers 0-255") from err
    frame = build_v2_command(sub, end, data)
    controller = _need_controller(hub, fixture)
    await _aux(hub, lambda: controller.send_payload(frame, dst=fixture.node))
    hub._log("tx", f"{fixture.light.name}: frame {frame.hex(' ')}")
    return {"type": "ack", "of": "lab.frame", "hex": frame.hex()}


@command("lab.record")
async def _lab_record(hub: Hub, client: Client, m: dict[str, Any]) -> dict[str, Any]:
    """Ask for any status record; the reply shows up in the log."""
    fixture = _fixture(hub, client, m)
    record = int(m.get("record", 0xA0)) & 0xFF
    controller = _need_controller(hub, fixture)
    frame = build_status_request(record=record)
    await _aux(hub, lambda: controller.send_payload(frame, dst=fixture.node))
    hub.lab_until = time.monotonic() + 2.0
    hub._log("tx", f"{fixture.light.name}: status request for record {record:02X}")
    return {"type": "ack", "of": "lab.record"}


@command("link.reconnect")
async def _reconnect(hub: Hub, client: Client, m: dict[str, Any]) -> None:
    hub.link.reconnect_now()


@command("visibility")
async def _visibility(hub: Hub, client: Client, m: dict[str, Any]) -> None:
    client.visible = bool(m.get("visible", True))


# -- lights ----------------------------------------------------------------------------------


@command("select")
async def _select(hub: Hub, client: Client, m: dict[str, Any]) -> dict[str, Any]:
    await hub.select(client, str(m.get("light") or ""), connect=bool(m.get("connect", False)))
    return {"type": "selected", "light": client.selected}


@command("lights.scan")
async def _scan(hub: Hub, client: Client, m: dict[str, Any]) -> dict[str, Any]:
    seconds = max(2.0, min(20.0, float(m.get("seconds") or 6)))
    try:
        nearby = await hub.scan(seconds)
    except Exception as err:
        raise CommandError(f"could not scan: {err}") from err
    return {"type": "ack", "of": "lights.scan", "nearby": nearby}


@command("lights.pair")
async def _pair(hub: Hub, client: Client, m: dict[str, Any]) -> dict[str, Any]:
    light = await hub.pair(client, str(m.get("address") or ""), str(m.get("name") or ""), str(m.get("radio_id") or ""))
    return {"type": "ack", "of": "lights.pair", "light": light.id}


@command("lights.import")
async def _import(hub: Hub, client: Client, m: dict[str, Any]) -> dict[str, Any]:
    light = await hub.import_keys(client, m.get("keys"), str(m.get("address") or ""), str(m.get("name") or ""),
                                  str(m.get("radio_id") or ""))
    return {"type": "ack", "of": "lights.import", "light": light.id}


@command("lights.rename")
async def _rename(hub: Hub, client: Client, m: dict[str, Any]) -> None:
    hub.rename(str(m.get("light") or ""), str(m.get("name") or ""))


@command("lights.model")
async def _model(hub: Hub, client: Client, m: dict[str, Any]) -> None:
    hub.set_model(str(m.get("light") or ""), str(m.get("radio_id") or ""))


@command("lights.place")
async def _place(hub: Hub, client: Client, m: dict[str, Any]) -> None:
    try:
        hub.place(str(m.get("light") or ""), float(m.get("x", 0.5)), float(m.get("y", 0.5)))
    except (KeyError, TypeError, ValueError) as err:
        raise CommandError(str(err)) from err


@command("lights.forget")
async def _forget(hub: Hub, client: Client, m: dict[str, Any]) -> None:
    await hub.forget(str(m.get("light") or ""))


@command("group.save")
async def _group_save(hub: Hub, client: Client, m: dict[str, Any]) -> dict[str, Any]:
    group = m.get("group")
    if not isinstance(group, dict):
        raise CommandError("expected a group")
    leader = str(m.get("leader") or client.selected or "")
    return {"type": "ack", "of": "group.save", "group": hub.save_group(group, leader=leader)}


@command("group.delete")
async def _group_delete(hub: Hub, client: Client, m: dict[str, Any]) -> None:
    hub.delete_group(str(m.get("id") or ""))


@command("group.match")
async def _group_match(hub: Hub, client: Client, m: dict[str, Any]) -> None:
    leader = _fixture(hub, client, m)
    targets = [str(t) for t in (m.get("targets") or [])]
    hub.match(leader.id, targets, [str(p) for p in (m.get("props") or [])])


# -- library --------------------------------------------------------------------------------


@command("settings")
async def _settings(hub: Hub, client: Client, m: dict[str, Any]) -> None:
    patch = m.get("patch") or {}
    if not isinstance(patch, dict) or {"light_states", "groups"} & set(patch):
        raise CommandError("those settings are managed by the studio")
    try:
        settings = hub.store.update_settings(patch)
    except ValueError as err:
        raise CommandError(str(err)) from err
    if "max_rate" in patch:
        hub.godox.set_max_rate(max(2.0, min(80.0, float(patch["max_rate"]))))
    if "relay_ttl" in patch and hub.controller is not None and hasattr(hub.controller, "relay_ttl"):
        hub.controller.relay_ttl = max(2, min(127, int(patch["relay_ttl"])))
    hub._broadcast({"type": "settings", "settings": settings})


@command("store.upsert")
async def _upsert(hub: Hub, client: Client, m: dict[str, Any]) -> dict[str, Any]:
    collection = str(m.get("collection"))
    if collection not in COLLECTIONS:
        raise CommandError(f"no collection {collection!r}")
    if collection == "looks":
        raise CommandError("save looks with looks.save")  # they are checked, and the current look kept in step (looks.py)
    if collection == "cues":
        raise CommandError("save cues with cues.save")  # checked, and the active cue kept in step (cues.py)
    item = m.get("item")
    if not isinstance(item, dict) or not str(item.get("name", "")).strip():
        raise CommandError("items need a name")
    if collection == "scenes" and "state" not in item:
        item = {**item, "state": _fixture(hub, client, m).state.model_dump()}
    stored = hub.store.upsert(collection, item)
    hub._broadcast({"type": "store", "collection": collection, "items": hub.store.items(collection)})
    return {"type": "ack", "of": "store.upsert", "item": stored}


@command("store.delete")
async def _delete(hub: Hub, client: Client, m: dict[str, Any]) -> None:
    collection = str(m.get("collection"))
    if collection not in COLLECTIONS:
        raise CommandError(f"no collection {collection!r}")
    if collection == "looks":
        raise CommandError("delete looks with looks.delete")
    if collection == "cues":
        raise CommandError("delete cues with cues.delete")
    hub.store.delete(collection, str(m.get("id")))
    hub._broadcast({"type": "store", "collection": collection, "items": hub.store.items(collection)})


@command("store.reorder")
async def _reorder(hub: Hub, client: Client, m: dict[str, Any]) -> None:
    collection = str(m.get("collection"))
    if collection not in COLLECTIONS:
        raise CommandError(f"no collection {collection!r}")
    hub.store.reorder(collection, [str(i) for i in m.get("ids", [])])
    hub._broadcast({"type": "store", "collection": collection, "items": hub.store.items(collection)})


@command("scene.apply")
async def _scene_apply(hub: Hub, client: Client, m: dict[str, Any]) -> None:
    fixture = _fixture(hub, client, m)
    scene = next((s for s in hub.store.items("scenes") if s["id"] == m.get("id")), None)
    if scene is None:
        raise CommandError("no such scene")
    if scene.get("effect"):
        fixture.engine.start_effect(scene["effect"], scene.get("params") or {})
        return
    # A scene may have been saved on a different model: fit it rather than refuse it.
    fade = float(m.get("fade", hub.store.settings["default_fade"]) or 0)
    _start(hub, fixture, _fitted(fixture, scene["state"]), fade)
