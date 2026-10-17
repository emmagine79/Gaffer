"""Keeping the app in step with the light. Pure: parsing and change detection.

Measured on an ML100R (2026-10-03), stock firmware:

* Record ``A0`` tracks the colour-temperature state: ``a0 BB KK ff 00 GG 00``
  -- brightness, kelvin / 100, and the green/magenta tint as a signed byte.
* Record ``A1`` tracks the HSI state: ``a1 BB HH HH SS ff 00`` -- brightness,
  hue little-endian across two bytes, saturation. Bi-colour lights have no
  colour mode, so earlier research never saw this record move.
* ``A2``-``A4`` (RGB, effect, gel) stay at their flash defaults.
* The light publishes a standard Generic OnOff Status (``82 04 xx``) every
  15 s on its own: a free heartbeat.

A record only says what that mode last held, not which mode is active, so a
reading is compared with the *previous reading* of the same record. A record
that did not move is stale and ignored; one that moved without the app having
commanded it was changed from outside -- the light's own panel -- and is
adopted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from godox_mesh_bt.protocol import parse_v2_payload

from .state import LightState

RECORD_CCT = 0xA0
RECORD_HSI = 0xA1
GENERIC_ONOFF_STATUS = bytes([0x82, 0x04])


@dataclass(frozen=True, slots=True)
class CctRecord:
    brightness: int
    kelvin: int
    gm: int

    def patch(self) -> dict[str, Any]:
        return {"mode": "cct", "brightness": self.brightness, "cct": {"kelvin": self.kelvin, "gm": self.gm}}

    def matches(self, state: LightState) -> bool:
        return (
            round(state.brightness) == self.brightness
            and state.cct.kelvin // 100 * 100 == self.kelvin  # the light truncates to 100 K, like the encoder
            and state.cct.gm == self.gm
        )


@dataclass(frozen=True, slots=True)
class HsiRecord:
    brightness: int
    hue: int
    sat: int

    def patch(self) -> dict[str, Any]:
        return {"mode": "hsi", "brightness": self.brightness, "hsi": {"hue": self.hue, "sat": self.sat}}

    def matches(self, state: LightState) -> bool:
        return (
            round(state.brightness) == self.brightness
            and round(state.hsi.hue) % 360 == self.hue % 360
            and round(state.hsi.sat) == self.sat
        )


Record = CctRecord | HsiRecord


def _signed(byte: int) -> int:
    return byte - 256 if byte > 127 else byte


def parse_record(v2: bytes) -> Record | None:
    """Decode a status reply's V2 frame, or None for records that carry nothing live."""
    try:
        parsed = parse_v2_payload(v2)
    except ValueError:
        return None
    d = parsed.data
    if parsed.model == RECORD_CCT:
        return CctRecord(brightness=d[0], kelvin=d[1] * 100, gm=_signed(d[4]))
    if parsed.model == RECORD_HSI:
        return HsiRecord(brightness=d[0], hue=d[1] | (d[2] << 8), sat=d[3])
    return None


def expected_record(frame: bytes) -> Record | None:
    """The record the light will hold after it accepts ``frame``.

    The records are copies of the last command of each kind, so a sent command
    predicts its own readback exactly:

        CCT  f0 BB KK (gm+50) circle GM tenths crc  ->  A0: BB, KK*100, GM
        HSI  f1 BB HL HH SS 00 tenths crc           ->  A1: BB, HH<<8|HL, SS
    """
    if len(frame) != 8:
        return None
    if frame[0] == 0xF0:
        return CctRecord(brightness=frame[1], kelvin=frame[2] * 100, gm=_signed(frame[5]))
    if frame[0] == 0xF1:
        return HsiRecord(brightness=frame[1], hue=frame[2] | (frame[3] << 8), sat=frame[4])
    return None


def parse_onoff(access_payload: bytes) -> bool | None:
    """Present state from a Generic OnOff Status message, else None."""
    if len(access_payload) >= 3 and access_payload[:2] == GENERIC_ONOFF_STATUS:
        return access_payload[2] != 0
    return None


class SyncTracker:
    """Decides whether a reading is news from outside or an echo of the app."""

    def __init__(self) -> None:
        self._last: dict[type, Record] = {}
        self._sent: dict[type, Record] = {}

    def reset(self) -> None:
        self._last.clear()
        self._sent.clear()

    def baseline(self, record: Record) -> None:
        self._last[type(record)] = record

    def expect(self, record: Record | None) -> None:
        """Note what the app just sent, so its readback is known to be an echo."""
        if record is not None:
            self._sent[type(record)] = record

    def observe(self, record: Record, state: LightState) -> dict[str, Any] | None:
        """A state patch when ``record`` shows a change the app did not make."""
        previous = self._last.get(type(record))
        self._last[type(record)] = record
        if previous is None or previous == record:
            return None
        if record == self._sent.get(type(record)):
            # The echo of what the app sent. Forget it, so a later change back
            # to this same value from the panel is not mistaken for an echo.
            del self._sent[type(record)]
            return None
        if record.matches(state):
            return None
        self._sent.pop(type(record), None)
        return record.patch()
