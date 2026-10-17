"""Regressions for bugs found in code review (2026-10-03). Each names its failure."""

from __future__ import annotations

import asyncio

import pytest

from lumen_studio.blend import blend
from lumen_studio.catalog import model_caps
from lumen_studio.engine import Engine
from lumen_studio.frames import mode_frame
from lumen_studio.pump import CommandPump
from lumen_studio.state import LightState, apply_patch
from lumen_studio.sync import CctRecord, SyncTracker, expected_record


@pytest.fixture(scope="module")
def caps():
    return model_caps("008F")


def test_reselecting_the_old_value_after_a_panel_change_is_sent(caps):
    """App sent 5600 K, panel moved to 3200 K (adopted), user clicks 5600 K again."""
    sent: list[bytes] = []

    async def run() -> None:
        async def sender(frame: bytes, dst: int | None = None) -> None:
            sent.append(frame)

        pump = CommandPump(caps, max_rate=1000)
        task = asyncio.create_task(pump.run())
        pump.attach(sender)
        s5600 = apply_patch(LightState(), {"cct": {"kelvin": 5600}}, caps)
        pump.submit(s5600)
        await asyncio.sleep(0.05)
        pump.forget()  # what the hub does when it adopts 3200 K from the light
        pump.submit(s5600)
        await asyncio.sleep(0.05)
        task.cancel()

    asyncio.run(run())
    assert sent.count(mode_frame(apply_patch(LightState(), {"cct": {"kelvin": 5600}}, caps), caps)) == 2


def test_a_panel_change_back_to_the_apps_value_is_adopted(caps):
    """A -> B -> A: the second A came from the panel and must not be taken for an echo."""
    tracker = SyncTracker()
    app = apply_patch(LightState(), {"brightness": 50, "cct": {"kelvin": 5600}}, caps)
    tracker.expect(expected_record(mode_frame(app, caps)))
    tracker.observe(CctRecord(50, 5600, 0), app)  # baseline
    assert tracker.observe(CctRecord(50, 5600, 0), app) is None  # echo
    adopted = apply_patch(app, tracker.observe(CctRecord(50, 3200, 0), app) or {}, caps)
    assert adopted.cct.kelvin == 3200
    assert tracker.observe(CctRecord(50, 5600, 0), adopted) is not None


def test_fading_between_two_off_states_never_switches_on(caps):
    off = LightState(power=False)
    assert blend(off, off.model_copy(update={"brightness": 80}), 0.5).power is False


def test_bad_colour_parameters_fall_back_to_defaults():
    from lumen_studio.effects import REGISTRY
    p = REGISTRY["breathe"].resolve({"color": "not-a-colour"})
    assert p["color"] == REGISTRY["breathe"].defaults()["color"]
    assert REGISTRY["palette"].resolve({"colors": ["#ff0000", "nope"]})["colors"] == ["#ff0000"]


def test_a_failing_effect_stops_instead_of_killing_the_clock(caps):
    box = {"state": LightState()}
    eng = Engine(caps, get_state=lambda: box["state"], apply=lambda s: box.update(state=s), on_change=lambda _s: None)
    eng.start_effect("breathe")
    eng.params["period"] = 0.0  # division by zero inside the effect
    eng.tick()
    assert eng.kind is None


def test_vault_sessions_start_above_anything_possibly_used(tmp_path):
    from godox_mesh_bt.state import MeshState

    from lumen_studio.link import SequenceVault
    path = tmp_path / "mesh.json"
    MeshState("00" * 16, "11" * 16, 1, 2, 100, 0).save(path)
    vault = SequenceVault(path, reserve=50)
    used = vault.state.next_sequence(10)  # a session sent ten
    vault.write(used)
    fresh = vault.fresh_session()
    assert fresh.sequence_number >= 150 > used.sequence_number
    assert MeshState.load(path).sequence_number > fresh.sequence_number


def test_vault_ignores_writes_from_a_rotated_away_source(tmp_path):
    import dataclasses

    from godox_mesh_bt.state import MeshState

    from lumen_studio.link import SequenceVault
    path = tmp_path / "mesh.json"
    MeshState("00" * 16, "11" * 16, 1, 2, 100, 0).save(path)
    vault = SequenceVault(path, reserve=50)
    vault.rotate()
    vault.write(dataclasses.replace(vault.state, provisioner_address=1, sequence_number=99999))
    assert vault.state.provisioner_address != 1


def test_a_change_during_a_fade_builds_on_where_the_fade_was_going(caps):
    from lumen_studio.commands import _patched

    class FakeHub:
        pass

    hub = FakeHub()
    hub.caps = caps
    hub.state = apply_patch(LightState(), {"mode": "hsi", "hsi": {"hue": 120}}, caps)  # mid-fade blend
    hub.engine = type("E", (), {"kind": "transition", "target": apply_patch(LightState(), {"cct": {"kelvin": 3200}}, caps)})()
    new = _patched(hub, {"brightness": 20})
    assert new.mode == "cct" and new.cct.kelvin == 3200 and new.brightness == 20


def test_an_unencodable_effect_parameter_is_rejected_at_the_door(caps):
    from lumen_studio.commands import CommandError, _patched

    hub = type("H", (), {})()
    hub.caps = caps
    hub.state = LightState()
    hub.engine = type("E", (), {"kind": None, "target": None})()
    with pytest.raises(CommandError):
        _patched(hub, {"mode": "fx", "fx": {"symbol": 5, "params": {"option": 1, "option_value": -1}}})


async def test_studio_controller_segments_long_frames(tmp_path):
    """Found on hardware: selecting a gel did nothing, because the 16-byte
    access payload went out as one oversized packet the light discarded."""
    from unittest.mock import AsyncMock, MagicMock

    from godox_mesh_bt.protocol import build_color_chip_command, build_hsi_command
    from godox_mesh_bt.state import MeshState

    from lumen_studio.transport import StudioController

    state = MeshState("98b2e7ef8211c6deca2401adbe52e715", "fa0a2c615756eca3f896ce061ed4d890", 1, 2, 700, 0)
    client = MagicMock()
    client.write_gatt_char = AsyncMock()
    client.is_connected = True
    ctl = StudioController("AA:BB", client_factory=lambda _a: client, state=state, gateway_node=2)
    assert (ctl.ttl_for(2), ctl.ttl_for(4)) == (0, 5)  # direct to the gateway, relayed to the rest
    ctl._client._client = client

    await ctl.send_payload(build_hsi_command(50, 200, 80))
    assert client.write_gatt_char.await_count == 1 and ctl.state.sequence_number == 701
    await ctl.send_payload(build_color_chip_command(50, brand=0, number=14, version=2, sub_brand=1))
    assert client.write_gatt_char.await_count == 3 and ctl.state.sequence_number == 703


@pytest.mark.parametrize("symbol", range(3, 17))
def test_every_builtin_effect_encodes_with_the_settings_the_ui_sends(caps, symbol):
    """Found on hardware: Explosion (and every effect with a Speed setting) crashed
    with "got multiple values for keyword argument 'speed'"."""
    from godox_mesh_bt.protocol import build_fx_command

    effect = next(e for e in caps.effects if e.symbol == symbol)
    params = {p["key"]: int(p["default"]) for p in effect.params}  # what the Effects tab sends
    state = apply_patch(LightState(), {"brightness": 40, "mode": "fx", "fx": {"symbol": symbol, "speed": None, "params": params}}, caps)
    frame = mode_frame(state, caps)
    rest = {k: v for k, v in params.items() if k != "speed"}
    assert frame == build_fx_command(symbol, 40, speed=params.get("speed"), effect_version=1, **rest)


def test_a_speed_change_reaches_the_frame(caps):
    slow = apply_patch(LightState(), {"mode": "fx", "fx": {"symbol": 13, "params": {"speed": 10}}}, caps)
    fast = apply_patch(LightState(), {"mode": "fx", "fx": {"symbol": 13, "params": {"speed": 90}}}, caps)
    assert mode_frame(slow, caps) != mode_frame(fast, caps)


def test_record_matching_truncates_kelvin_like_the_light(caps):
    """The CCT frame carries kelvin // 100, so 4950 K reads back as 4900 K."""
    state = apply_patch(LightState(), {"brightness": 40, "cct": {"kelvin": 4950}}, caps)
    assert CctRecord(40, 4900, 0).matches(state)
    assert not CctRecord(40, 5000, 0).matches(state)
