"""Yongnuo BLE frames. Pure functions: bytes in, bytes out, nothing opens Bluetooth.

Two frame variants, both taking the light's channel (0 to 255):

* decimal (9 bytes): ``AE 03 09 ch kk kk bb A0 bt``. Ported from
  asidjwiaijd/yongnuo-light-control (MIT), yn_light_control/lib/ble_protocol.dart
  ``buildColorTempDecimalCommand`` and esp32_circadian/main/yn_protocol.h. Licence in
  THIRD-PARTY/yongnuo-light-control/LICENSE. ``kk kk`` is the Kelvin as a big-endian
  16-bit number, ``bb`` is whole percent and ``bt`` is the extra tenths of a percent.
* plain (8 bytes): ``AE 03 08 ch kk kk bb 56``. The layout is a fact read from the
  Mifaiyang/yongnuo-light-homekit-bridge README (no licence, so no code is taken from
  it): ``bb`` is whole percent 0 to 100. Power frames come from the model file.
"""

from __future__ import annotations

SERVICE_UUID = "f000aa60-0451-4000-b000-000000000000"
WRITE_UUID = "f000aa61-0451-4000-b000-000000000000"
NOTIFY_UUID = "f000aa63-0451-4000-b000-000000000000"

FRAME_HEADER = 0xAE
COLOUR_TEMP_FAMILY = 0x03
DECIMAL_FRAME_LENGTH = 0x09
PLAIN_FRAME_LENGTH = 0x08
DECIMAL_MARKER = 0xA0
PLAIN_TRAILER = 0x56

#: Channel is one byte. Source: the Dart encoder asserts 0..0xFF.
CHANNEL_MAX = 0xFF
#: Hardware range of the light the Dart code was verified on (yn_protocol.h) and the
#: range the Mifaiyang README gives for the YN150. Model files carry their own.
DEFAULT_MIN_KELVIN = 2700
DEFAULT_MAX_KELVIN = 6500


def check_channel(channel: int) -> int:
    """The channel as an int in 0..255, or ValueError. Booleans and floats are refused."""
    if isinstance(channel, bool) or not isinstance(channel, int) or not 0 <= channel <= CHANNEL_MAX:
        raise ValueError("The Yongnuo channel must be a whole number from 0 to 255.")
    return channel


def clamp_kelvin(kelvin: float, lo: int = DEFAULT_MIN_KELVIN, hi: int = DEFAULT_MAX_KELVIN) -> int:
    return max(lo, min(hi, round(kelvin)))


def clamp_percent(percent: float) -> float:
    return max(0.0, min(100.0, float(percent)))


def encode_decimal(
    channel: int,
    kelvin: float,
    brightness: float,
    *,
    min_kelvin: int = DEFAULT_MIN_KELVIN,
    max_kelvin: int = DEFAULT_MAX_KELVIN,
) -> bytes:
    """Decimal variant. ``brightness`` is percent (0 to 100, one decimal place kept)."""
    ch = check_channel(channel)
    k = clamp_kelvin(kelvin, min_kelvin, max_kelvin)
    tenths = round(clamp_percent(brightness) * 10)
    return bytes([
        FRAME_HEADER,
        COLOUR_TEMP_FAMILY,
        DECIMAL_FRAME_LENGTH,
        ch,
        (k >> 8) & 0xFF,
        k & 0xFF,
        (tenths // 10) & 0xFF,
        DECIMAL_MARKER,
        (tenths % 10) & 0xFF,
    ])


def encode_plain(
    channel: int,
    kelvin: float,
    brightness: float,
    *,
    min_kelvin: int = DEFAULT_MIN_KELVIN,
    max_kelvin: int = DEFAULT_MAX_KELVIN,
) -> bytes:
    """Plain variant (YN150WY layout). ``brightness`` is percent, sent as a whole number."""
    ch = check_channel(channel)
    k = clamp_kelvin(kelvin, min_kelvin, max_kelvin)
    return bytes([
        FRAME_HEADER,
        COLOUR_TEMP_FAMILY,
        PLAIN_FRAME_LENGTH,
        ch,
        (k >> 8) & 0xFF,
        k & 0xFF,
        round(clamp_percent(brightness)),
        PLAIN_TRAILER,
    ])


def encode_power(template: str, channel: int) -> bytes:
    """A power frame from a model-file template such as ``AE 01 06 {ch} 01 56``."""
    ch = check_channel(channel)
    return bytes.fromhex(template.replace("{ch}", f"{ch:02X}").replace(" ", ""))
