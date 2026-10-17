"""Godox bytes. Pure: the same arguments always give the same bytes, with no I/O and no clock.

These are thin, named wrappers over lumen's frame builders (``gaffer.frames``) and the
library's access layer, so a byte test can call them without a light, a link or a loop.
"""

from __future__ import annotations

from godox_mesh_bt.controller import REQUEST_OPCODE
from godox_mesh_bt.crypto import build_vendor_access_payload

from ...catalog import ModelCaps
from ...frames import mode_frame, power_frame
from ...pump import plan_frames
from ...state import LightState


def encode_power(on: bool) -> bytes:
    """The Godox frame that switches the light on or off."""
    return power_frame(on)


def encode_state(state: LightState, caps: ModelCaps) -> bytes:
    """The one frame that puts the light into ``state``'s mode, brightness and colour."""
    return mode_frame(state, caps)


def encode_frames(
    state: LightState, caps: ModelCaps, *, last_power: bool | None = None, last_mode_frame: bytes | None = None
) -> tuple[bytes, ...]:
    """The frames needed to reach ``state`` from what was last sent (nothing sent yet: everything)."""
    return plan_frames(state, caps, last_power=last_power, last_mode_frame=last_mode_frame)


def encode_access_payload(frame: bytes) -> bytes:
    """A frame as it rides the mesh: the vendor opcode in front of the Godox payload."""
    return build_vendor_access_payload(REQUEST_OPCODE, frame)
