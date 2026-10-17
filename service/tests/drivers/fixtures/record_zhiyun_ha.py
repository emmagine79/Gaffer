"""Record what didim99/HA-Zhiyun-Light writes for fixed inputs. Run once; commit the JSON it prints.

    python record_zhiyun_ha.py <path to a clone of HA-Zhiyun-Light> > zhiyun_ha_frames.json

Needs `bleak` and `bleak-retry-connector` installed (the HA module imports them).
It loads the real protocol.py and zhiyun_ble.py from the clone and drives the real
ZhiyunDevice against a fake GATT client that records every write. Nothing touches Bluetooth.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import subprocess
import sys
import types
from pathlib import Path

clone = Path(sys.argv[1])
pkg_dir = clone / "custom_components" / "zhiyun_ble"
commit = subprocess.run(["git", "-C", str(clone), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()

pkg = types.ModuleType("zb")
pkg.__path__ = [str(pkg_dir)]
sys.modules["zb"] = pkg


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"zb.{name}", pkg_dir / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"zb.{name}"] = mod
    spec.loader.exec_module(mod)
    return mod


p = load("protocol")
zb = load("zhiyun_ble")


class Char:
    def __init__(self, uuid): self.uuid = uuid


class Service:
    def get_characteristic(self, uuid): return Char(uuid)


class Services:
    def get_service(self, uuid): return Service()


class FakeClient:
    is_connected = True
    services = Services()

    def __init__(self): self.writes: list[str] = []

    async def start_notify(self, *_): pass
    async def disconnect(self): pass

    async def write_gatt_char(self, char, data, response=True):
        assert response is False and char.uuid == p.WRITE_CHAR_UUID
        self.writes.append(bytes(data).hex())


async def run(scenario):
    client = FakeClient()

    async def establish(*_a, **_k): return client

    async def noop(*_a, **_k): pass

    zb.establish_connection = establish
    zb.close_stale_connections = noop
    zb._POWER_SETTLE_DELAY = zb._INIT_STEP_DELAY = 0
    dev = zb.ZhiyunDevice(types.SimpleNamespace(address="AA:BB:CC:00:00:01"), "PL109_TEST", idle_disconnect_after=3600)
    await scenario(dev)
    await dev.async_disconnect()
    return client.writes


async def _on(d):
    await d.async_turn_on(brightness=37.5, color_temp_kelvin=4300)


def seq(*calls):
    """Run HA calls one after another on the same device."""
    async def go(d):
        for call in calls:
            await call(d)
    return go


scenarios = {
    "on_37_5_4300": seq(_on),
    "on_then_brightness_80": seq(_on, lambda d: d.async_set_brightness(80)),
    "on_then_cct_3200": seq(_on, lambda d: d.async_set_color_temp_kelvin(3200)),
    "on_then_brightness_0": seq(_on, lambda d: d.async_set_brightness(0)),
    "on_then_off": seq(_on, lambda d: d.async_turn_off()),
    "on_off_on_again": seq(_on, lambda d: d.async_turn_off(), lambda d: d.async_turn_on(brightness=37.5)),
    "off_first": seq(lambda d: d.async_turn_off()),
    "on_clamped_250_9000": seq(lambda d: d.async_turn_on(brightness=250, color_temp_kelvin=9000)),
    "on_clamped_below_1000": seq(lambda d: d.async_turn_on(brightness=37.5, color_temp_kelvin=1000)),
}

out = {
    "source": "didim99/HA-Zhiyun-Light",
    "commit": commit,
    "note": "writes are hex frames in order; the first 5 are the connect handshake",
    "packets": {},
    "sessions": {},
}
# protocol.build_packet for fixed sequences: the pure frame bytes.
for seq in (0, 1, 7, 65535):
    out["packets"][f"seq{seq}"] = {
        "power_on": p.build_packet(p.Command.POWER_STATE, p.encode_power(True), seq).hex(),
        "power_off": p.build_packet(p.Command.POWER_STATE, p.encode_power(False), seq).hex(),
        "brightness_0": p.build_packet(p.Command.SET_BRIGHTNESS, p.encode_brightness(0), seq).hex(),
        "brightness_37_5": p.build_packet(p.Command.SET_BRIGHTNESS, p.encode_brightness(37.5), seq).hex(),
        "brightness_100": p.build_packet(p.Command.SET_BRIGHTNESS, p.encode_brightness(100), seq).hex(),
        "cct_2700": p.build_packet(p.Command.SET_COLOR_TEMP, p.encode_color_temp(2700), seq).hex(),
        "cct_4300": p.build_packet(p.Command.SET_COLOR_TEMP, p.encode_color_temp(4300), seq).hex(),
        "cct_6500": p.build_packet(p.Command.SET_COLOR_TEMP, p.encode_color_temp(6500), seq).hex(),
        "query": p.build_packet(p.Command.READ_DEVICE_STATE, p.encode_query(), seq).hex(),
    }
out["parsed"] = {}
for name, hexframe in out["packets"]["seq1"].items():
    r = p.parse_frame(bytes.fromhex(hexframe))
    out["parsed"][name] = {"command": r.command, "sequence": r.sequence, "payload": r.payload.hex()}
bad = bytearray.fromhex(out["packets"]["seq1"]["power_on"])
bad[-1] ^= 0xFF
try:
    p.parse_frame(bytes(bad))
    out["bad_crc_rejected"] = False
except p.ProtocolError:
    out["bad_crc_rejected"] = True
out["model_names"] = dict(p.MODEL_NAMES)
for name, fn in scenarios.items():
    out["sessions"][name] = asyncio.run(run(fn))
print(json.dumps(out, indent=1))
