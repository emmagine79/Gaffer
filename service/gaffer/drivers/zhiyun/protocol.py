"""Zhiyun BLE wire protocol: pure functions, no Bluetooth, no state.

Ported from didim99/HA-Zhiyun-Light, custom_components/zhiyun_ble/protocol.py at
commit 7ca51ea (MIT, licence in THIRD-PARTY/HA-Zhiyun-Light/LICENSE). The frame
layout also matches zyframe.py, recovered from the Zhiyun app's native library.

Frame, all multi-byte fields little-endian::

    24 3C | len u16 | 00 01 | seq u16 | cid u16 | object u16 | op u8 | args | crc u16

``len`` is the size of everything between ``len`` and the CRC. The CRC is
CRC-16/XMODEM over the bytes from ``00 01`` to the end of the args.

Differences from the original, all for input safety: encoders refuse NaN,
infinity and non-numbers, clamp to a range the caller supplies, and the op byte
is a parameter (0x01 as in HA-Zhiyun-Light, or 0x33 as in zhiyun-light-control).
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from enum import IntEnum
from typing import Final

# --- Connection (HA-Zhiyun-Light zhiyun_ble.py / protocol.py) ----------------------

SERVICE_UUID: Final = "0000fee9-0000-1000-8000-00805f9b34fb"
WRITE_CHAR_UUID: Final = "d44bc439-abfd-45a2-b575-925416129600"
NOTIFY_CHAR_UUID: Final = "d44bc439-abfd-45a2-b575-925416129601"

# --- Frame constants ----------------------------------------------------------------

_MAGIC: Final = b"\x24\x3c"
_DIRECTION_REQUEST: Final = b"\x00\x01"
CONTROL_OBJECT: Final = 0x8003
#: The op byte after the object id. HA-Zhiyun-Light sends 0x01; zhiyun-light-control
#: (aaditagrawal) defaults to 0x33. Which one a light wants is a model-file setting.
OP_LEGACY: Final = 0x01
OP_DEFAULT: Final = 0x33
VALID_OPS: Final = (OP_LEGACY, OP_DEFAULT)
_HEADER_LEN: Final = 4
_FRAME_OVERHEAD: Final = _HEADER_LEN + 2
_MAX_SEQUENCE: Final = 0xFFFF


class Command(IntEnum):
    SET_BRIGHTNESS = 0x1001
    SET_COLOR_TEMP = 0x1002
    POWER_STATE = 0x1008
    #: Max Mode (turbo): one value byte after the object and op, 1 on and 0 off. Read with ``encode_query``.
    #: Named QUERY_BRIGHTNESS here until 18 Oct 2026; the handshake still sends it as a read (docs/research/molus-turbo.md).
    MAX_MODE = 0x1009
    READ_DEVICE_STATE = 0x0006
    GET_DEVICE_INFO = 0x2005
    GET_DEVICE_NAME = 0x2003
    GET_FIRMWARE = 0x8001


# --- Ranges --------------------------------------------------------------------------

BRIGHTNESS_MIN: Final[float] = 0.0
BRIGHTNESS_MAX: Final[float] = 100.0
COLOR_TEMP_MIN_KELVIN: Final[int] = 2700
COLOR_TEMP_MAX_KELVIN: Final[int] = 6500
_U16_MAX: Final = 0xFFFF


class ProtocolError(ValueError):
    """A frame could not be decoded, or an encoder input was not usable."""


# --- CRC -----------------------------------------------------------------------------


def crc16_xmodem(data: bytes) -> int:
    """CRC-16/XMODEM: poly 0x1021, init 0, no reflection, no xor-out."""
    crc = 0
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


# --- Encoding ------------------------------------------------------------------------


def build_packet(command: Command | int, payload: bytes, sequence: int) -> bytes:
    """One complete frame for ``command`` carrying ``payload``."""
    body = (
        _DIRECTION_REQUEST
        + struct.pack("<H", sequence & _MAX_SEQUENCE)
        + struct.pack("<H", int(command))
        + payload
    )
    return _MAGIC + struct.pack("<H", len(body)) + body + struct.pack("<H", crc16_xmodem(body))


def _op(op: int) -> int:
    if isinstance(op, bool) or op not in VALID_OPS:
        raise ProtocolError(f"op byte must be one of {[hex(o) for o in VALID_OPS]}, not {op!r}")
    return op


def _control(op: int) -> bytes:
    return struct.pack("<HB", CONTROL_OBJECT, _op(op))


def _number(value: object, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProtocolError(f"{what} must be a number, not {type(value).__name__}")
    if not math.isfinite(value):
        raise ProtocolError(f"{what} must be a finite number")
    return float(value)


def encode_power(on: bool, op: int = OP_LEGACY) -> bytes:
    return _control(op) + (b"\x01" if on else b"\x00")


def encode_max_mode(on: bool, op: int = OP_LEGACY) -> bytes:
    """Max Mode: the control object and op, then one byte, 1 for on and 0 for off."""
    if not isinstance(on, bool):
        raise ProtocolError(f"max mode must be true or false, not {type(on).__name__}")
    return _control(op) + (b"\x01" if on else b"\x00")


def encode_brightness(
    value: float,
    op: int = OP_LEGACY,
    lo: float = BRIGHTNESS_MIN,
    hi: float = BRIGHTNESS_MAX,
) -> bytes:
    """Brightness as a float32, clamped to ``lo``..``hi`` (percent)."""
    clamped = max(lo, min(hi, _number(value, "brightness")))
    return _control(op) + struct.pack("<f", clamped)


def encode_color_temp(
    kelvin: int,
    op: int = OP_LEGACY,
    lo: int = COLOR_TEMP_MIN_KELVIN,
    hi: int = COLOR_TEMP_MAX_KELVIN,
) -> bytes:
    """Colour temperature as a u16, clamped to the model's ``lo``..``hi`` kelvin."""
    clamped = max(lo, min(hi, int(_number(kelvin, "colour temperature"))))
    if not 0 <= clamped <= _U16_MAX:
        raise ProtocolError("colour temperature range does not fit in 16 bits")
    return _control(op) + struct.pack("<H", clamped)


def encode_query() -> bytes:
    return struct.pack("<HBB", CONTROL_OBJECT, 0x00, 0x00)


# --- Decoding ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Response:
    command: int
    sequence: int
    payload: bytes


def parse_frame(data: bytes) -> Response:
    """Decode a notification frame. Raises ProtocolError on a short, wrong-length or bad-CRC frame."""
    if len(data) < _HEADER_LEN + 6 + 2:
        raise ProtocolError(f"frame too short: {len(data)} bytes")
    if data[:2] != _MAGIC:
        raise ProtocolError("invalid magic header")
    declared = int.from_bytes(data[2:4], "little")
    if len(data) != _HEADER_LEN + declared + 2:
        raise ProtocolError(f"length mismatch: header says {declared}, got {len(data) - _FRAME_OVERHEAD}")
    body = data[_HEADER_LEN:-2]
    if int.from_bytes(data[-2:], "little") != crc16_xmodem(body):
        raise ProtocolError("CRC mismatch")
    return Response(
        command=int.from_bytes(body[4:6], "little"),
        sequence=int.from_bytes(body[2:4], "little"),
        payload=body[6:],
    )


def decode_brightness_response(payload: bytes) -> float | None:
    return struct.unpack("<f", payload[3:7])[0] if len(payload) >= 7 else None


def decode_color_temp_response(payload: bytes) -> int | None:
    return int.from_bytes(payload[3:5], "little") if len(payload) >= 5 else None


def decode_max_mode_response(payload: bytes) -> bool | None:
    """The answer to a Max Mode read or write: object (2 bytes), op, then 1 on or 0 off.

    Captured from a MOLUS G200, 18 Oct 2026: off ``03 80 00 00``, on ``03 80 00 01``.
    """
    return payload[3] == 0x01 if len(payload) >= 4 else None


def decode_power_response(payload: bytes) -> bool | None:
    return payload[2] == 0x01 if len(payload) >= 3 else None
