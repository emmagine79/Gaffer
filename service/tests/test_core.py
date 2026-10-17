"""Catalogue, state, frames and pump: everything below the link, no hardware."""

from __future__ import annotations

import asyncio

import pytest
from godox_mesh_bt.protocol import (
    build_cct_command,
    build_fx_command,
    build_hsi_command,
    build_rgb_wide_command,
)

from gaffer.catalog import gels, model_caps
from gaffer.frames import POWER_OFF, POWER_ON, mode_frame
from gaffer.pump import CommandPump, plan_frames
from gaffer.state import LightState, StateError, apply_patch


@pytest.fixture(scope="module")
def caps():
    return model_caps("008F")


# -- catalogue ---------------------------------------------------------------


def test_ml100r_caps_match_the_generated_table(caps):
    assert caps.name == "ML100R"
    assert (caps.min_kelvin, caps.max_kelvin) == (1800, 10000)
    assert caps.has_tint
    assert caps.effect_version == 1
    assert caps.effect_symbols == frozenset(range(3, 17))
    assert caps.rgb_display == 2


def test_every_ml100r_effect_exposes_its_v3_parameters(caps):
    lightning = next(e for e in caps.effects if e.name == "Lightning")
    assert [p["key"] for p in lightning.params] == ["frequency", "trigger", "twinkling", "temperature"]


def test_gels_carry_their_true_colour(caps):
    table = gels(caps.color_chip_version)
    assert len(table) == 318
    assert all(g["hex"].startswith("#") and len(g["hex"]) == 7 for g in table)
    assert sum(g["hex"] == "#808080" for g in table) == 0  # every gel joined
    cor = next(g for g in table if g["label"] == "L-GEL COR. 286")
    assert cor["hex"] == "#ffb464"


# -- state ------------------------------------------------------------------


def test_patch_is_immutable_and_deep(caps):
    base = LightState()
    changed = apply_patch(base, {"cct": {"kelvin": 3200}}, caps)
    assert base.cct.kelvin == 5600
    assert changed.cct.kelvin == 3200
    assert changed.cct.gm == base.cct.gm


def test_kelvin_outside_the_model_range_is_rejected(caps):
    with pytest.raises(StateError, match="1800-10000"):
        apply_patch(LightState(), {"cct": {"kelvin": 1500}}, caps)


def test_effect_must_belong_to_the_model(caps):
    with pytest.raises(StateError):
        apply_patch(LightState(), {"mode": "fx", "fx": {"symbol": 1}}, caps)
    with pytest.raises(StateError, match="parameter"):
        apply_patch(LightState(), {"mode": "fx", "fx": {"symbol": 10, "params": {"ember": 3}}}, caps)


def test_mode_settings_survive_a_mode_switch(caps):
    s = apply_patch(LightState(), {"mode": "hsi", "hsi": {"hue": 200}}, caps)
    s = apply_patch(s, {"mode": "cct"}, caps)
    assert s.hsi.hue == 200


# -- frames: byte-exact against the library ------------------------------------


def test_cct_frame_matches_library(caps):
    s = apply_patch(LightState(), {"brightness": 40, "cct": {"kelvin": 3200, "gm": -20}}, caps)
    assert mode_frame(s, caps) == build_cct_command(
        40, 3200, gm=-20, supports_gm=True, min_kelvin=1800, max_kelvin=10000
    )


def test_hsi_frame_matches_library(caps):
    s = apply_patch(LightState(), {"mode": "hsi", "brightness": 60, "hsi": {"hue": 359.6, "sat": 80}}, caps)
    assert mode_frame(s, caps) == build_hsi_command(60, 0, 80)  # 359.6 rounds to 360 -> wraps to 0


def test_rgbw_uses_the_wide_frame_on_ml100r(caps):
    s = apply_patch(LightState(), {"mode": "rgbw", "rgbw": {"r": 1000, "g": 0, "b": 500, "w": 250}}, caps)
    assert mode_frame(s, caps) == build_rgb_wide_command(50, 1000, 0, 500, extra=(250, 0, 0))


def test_fx_frame_passes_parameters(caps):
    s = apply_patch(
        LightState(), {"mode": "fx", "fx": {"symbol": 6, "params": {"frequency": 40}}}, caps
    )
    assert mode_frame(s, caps) == build_fx_command(6, 50, effect_version=1, frequency=40)


# -- pump ------------------------------------------------------------------------


def test_plan_sends_power_only_when_it_changes(caps):
    s = LightState()
    first = plan_frames(s, caps, last_power=None, last_mode_frame=None)
    assert first[0] == POWER_ON and len(first) == 2
    again = plan_frames(s, caps, last_power=True, last_mode_frame=first[1])
    assert again == ()
    off = plan_frames(s.model_copy(update={"power": False}), caps, last_power=True, last_mode_frame=first[1])
    assert off == (POWER_OFF,)


class FakeSender:
    def __init__(self, fail_after: int | None = None) -> None:
        self.frames: list[bytes] = []
        self.fail_after = fail_after

    async def __call__(self, frame: bytes, dst: int | None = None) -> None:
        if self.fail_after is not None and len(self.frames) >= self.fail_after:
            raise ConnectionError("link down")
        self.frames.append(frame)


async def _drain(pump: CommandPump, ticks: int = 20) -> None:
    for _ in range(ticks):
        await asyncio.sleep(0.01)


async def test_pump_coalesces_to_the_latest_state(caps):
    pump = CommandPump(caps, max_rate=1000)
    sender = FakeSender()
    task = asyncio.create_task(pump.run())
    for k in range(2000, 2100):
        pump.submit(LightState(cct={"kelvin": k}))
    pump.attach(sender)
    await _drain(pump)
    task.cancel()
    assert sender.frames[-1] == mode_frame(LightState(cct={"kelvin": 2099}), caps)
    assert len(sender.frames) == 2  # power + one mode frame, not 100


async def test_pump_detaches_on_failure_and_resends_on_reattach(caps):
    failures: list[Exception] = []
    pump = CommandPump(caps, max_rate=1000, on_send_failure=failures.append)
    task = asyncio.create_task(pump.run())
    pump.attach(FakeSender(fail_after=1))
    pump.submit(LightState())
    await _drain(pump)
    assert not pump.attached
    assert len(failures) == 1  # reported once, no hot retry loop
    healthy = FakeSender()
    pump.attach(healthy)
    await _drain(pump)
    task.cancel()
    assert healthy.frames[0] == POWER_ON  # state re-asserted on the new link
    assert len(healthy.frames) == 2


async def test_aux_jobs_run_and_resolve(caps):
    pump = CommandPump(caps, max_rate=1000)
    task = asyncio.create_task(pump.run())
    pump.attach(FakeSender())

    async def job() -> str:
        return "status"

    assert await asyncio.wait_for(pump.submit_aux(job), 1) == "status"
    task.cancel()


# -- sequence vault ------------------------------------------------------------------


def _mesh_state(path, seq, src=1):
    from godox_mesh_bt.state import MeshState
    MeshState("00" * 16, "11" * 16, src, 2, seq, 0).save(path)


def test_vault_persists_ahead_and_never_behind(tmp_path):
    from godox_mesh_bt.state import MeshState

    from gaffer.link import SequenceVault
    path = tmp_path / "mesh.json"
    _mesh_state(path, 500)
    vault = SequenceVault(path, reserve=100)
    assert MeshState.load(path).sequence_number == 600  # reserved before any send
    for seq in range(501, 650):
        vault.write(vault.state.next_sequence())
        assert MeshState.load(path).sequence_number > vault.state.sequence_number - 1


def test_vault_rotates_to_a_fresh_source_when_spent(tmp_path):
    from godox_mesh_bt.state import MeshState

    from gaffer.link import ROTATE_AT, ROTATION_BASE, SequenceVault
    path = tmp_path / "mesh.json"
    _mesh_state(path, ROTATE_AT + 5)
    vault = SequenceVault(path, reserve=10)
    assert vault.needs_rotation
    assert vault.rotate() == ROTATION_BASE
    saved = MeshState.load(path)
    assert (saved.provisioner_address, saved.sequence_number) == (ROTATION_BASE, 10)
    assert not vault.needs_rotation


async def test_a_write_from_a_dead_link_cannot_detach_the_new_one(caps):
    release = asyncio.Event()

    async def slow_failing(frame: bytes, dst: int | None = None) -> None:
        await release.wait()
        raise ConnectionError("old link died")

    failures: list[Exception] = []
    pump = CommandPump(caps, max_rate=1000, on_send_failure=failures.append)
    task = asyncio.create_task(pump.run())
    pump.attach(slow_failing)
    pump.submit(LightState())
    await _drain(pump, 5)
    healthy = FakeSender()
    pump.attach(healthy)  # reconnect while the old write hangs
    release.set()
    await _drain(pump)
    task.cancel()
    assert pump.attached and failures == []


async def test_a_godox_light_gets_time_to_switch_on_before_its_level_frame(caps):
    # Captain, 18 Oct 2026: the LA150Bi often needed several presses of On. Its level frame followed the
    # power-on 33 ms later; ha-godox-mesh (MIT) gives a light 0.1 s to finish switching on first.
    now = [0.0]
    sent: list[tuple[float, bytes]] = []

    async def advance(seconds: float) -> None:
        now[0] += seconds

    async def send(frame: bytes, _node: int | None) -> None:
        sent.append((now[0], frame))

    pump = CommandPump(caps, max_rate=30, clock=lambda: now[0], sleep=advance)
    task = asyncio.create_task(pump.run())
    pump.attach(send)
    pump.submit(LightState(power=True, brightness=60))
    await _drain(pump)
    task.cancel()
    assert [frame for _at, frame in sent][:1] == [POWER_ON] and len(sent) == 2
    assert sent[1][0] - sent[0][0] >= 0.1
