"""Lower-transport segmentation for access payloads longer than one packet.

An unsegmented access message carries at most 11 bytes (3-byte vendor opcode
plus an 8-byte V2 frame). Gel, wide-RGB and multi-parameter effect frames are
longer; packed unsegmented they are malformed and the light drops them
silently. Found on a real ML100R: selecting a gel did nothing.
"""

from __future__ import annotations

import pytest

from godox_mesh_bt.crypto import (
    aes_ccm_decrypt,
    build_vendor_access_payload,
    decrypt_network_pdu,
    deobfuscate,
    k2,
    k4,
    pack_proxy_network_pdu,
    pack_proxy_network_pdus,
)
from godox_mesh_bt.protocol import build_color_chip_command, build_hsi_command

NET_KEY = bytes.fromhex("98b2e7ef8211c6deca2401adbe52e715")
APP_KEY = bytes.fromhex("fa0a2c615756eca3f896ce061ed4d890")
OPCODE = 0x0211F0


def _open(proxy_pdu: bytes) -> tuple[int, int, bytes]:
    """(seq, dst, lower transport PDU) from one proxy PDU."""
    assert proxy_pdu[0] == 0x00  # proxy SAR complete, network PDU
    nid, enc_key, priv_key = k2(NET_KEY)
    network = deobfuscate(proxy_pdu[1:], priv_key, 0)
    assert network[0] & 0x7F == nid
    dst, lower = decrypt_network_pdu(network, enc_key, 0)
    return int.from_bytes(network[2:5], "big"), dst, lower


def test_short_payloads_are_unchanged():
    access = build_vendor_access_payload(OPCODE, build_hsi_command(50, 200, 80))
    assert len(access) == 11
    single = pack_proxy_network_pdu(access, NET_KEY, APP_KEY, 0, 1000, 1, 2, 0)
    assert pack_proxy_network_pdus(access, NET_KEY, APP_KEY, 0, 1000, 1, 2, 0) == [single]


def test_a_gel_command_is_split_into_valid_segments_that_reassemble():
    access = build_vendor_access_payload(
        OPCODE, build_color_chip_command(50, brand=0, number=14, version=2, sub_brand=1)
    )
    assert len(access) == 16
    seq0 = 0x12345
    pdus = pack_proxy_network_pdus(access, NET_KEY, APP_KEY, 0, seq0, 1, 2, 0)
    assert len(pdus) == 2  # 16 + 4-byte MIC = 20 bytes -> 12 + 8

    upper = b""
    for index, pdu in enumerate(pdus):
        seq, dst, lower = _open(pdu)
        assert seq == seq0 + index  # each segment spends its own sequence number
        assert dst == 2
        assert lower[0] == 0x80 | 0x40 | k4(APP_KEY)  # SEG=1, AKF=1, AID
        header = int.from_bytes(lower[1:4], "big")
        assert header >> 23 == 0  # SZMIC: 32-bit TransMIC
        assert (header >> 10) & 0x1FFF == seq0 & 0x1FFF  # SeqZero from SeqAuth
        assert (header >> 5) & 0x1F == index  # SegO
        assert header & 0x1F == len(pdus) - 1  # SegN
        assert len(lower) <= 16  # fits a network PDU
        upper += lower[4:]

    nonce = bytes([0x01, 0x00]) + seq0.to_bytes(3, "big") + (1).to_bytes(2, "big") + (2).to_bytes(2, "big") + (0).to_bytes(4, "big")
    assert aes_ccm_decrypt(APP_KEY, nonce, upper, 4) == access


def test_payloads_beyond_32_segments_are_refused():
    with pytest.raises(ValueError):
        pack_proxy_network_pdus(bytes(400), NET_KEY, APP_KEY, 0, 1, 1, 2, 0)


async def test_controller_sends_every_segment_and_spends_a_number_each(tmp_path):
    from unittest.mock import AsyncMock, MagicMock

    from godox_mesh_bt.controller import GodoxController
    from godox_mesh_bt.state import MeshState

    state_file = tmp_path / "mesh_state.json"
    MeshState(NET_KEY.hex(), APP_KEY.hex(), 1, 2, 500, 0).save(state_file)
    client = MagicMock()
    client.connect = AsyncMock()
    client.write_gatt_char = AsyncMock()
    client.is_connected = True
    controller = GodoxController("AA:BB", state_file, client_factory=lambda _a: client)
    controller._client._client = client

    await controller.send_payload(build_color_chip_command(50, brand=0, number=14, version=2, sub_brand=1))

    assert client.write_gatt_char.await_count == 2
    seqs = [_open(c.args[1])[0] for c in client.write_gatt_char.await_args_list]
    assert seqs == [500, 501]
    assert MeshState.load(state_file).sequence_number == 502
