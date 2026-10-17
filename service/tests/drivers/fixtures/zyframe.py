#!/usr/bin/env python3
"""Build a Zhiyun light command frame, as recovered from libzylink.so (ZY Vega 1.1.7).

Layout (all u16 little-endian):
  24 3C | len | 00 01 | seq | cid | dev_id | op | args... | crc16
  len = payload + 6, where payload = dev_id + op + args
  crc = CRC-16/XMODEM over bytes 4 .. end of payload
Unverified on hardware.
"""
import struct
import sys


def crc16_xmodem(data: bytes) -> int:
    crc = 0
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return crc


def frame(cid: int, dev_id: int, op: int, args: bytes, seq: int) -> bytes:
    payload = struct.pack("<HB", dev_id, op) + args
    body = struct.pack("<HHH", 0x0100, seq, cid) + payload
    head = struct.pack("<HH", 0x3C24, len(payload) + 6)
    return head + body + struct.pack("<H", crc16_xmodem(body))


def rgb_set(dev_id: int, r: int, g: int, b: int, seq: int = 0) -> bytes:
    return frame(0x1003, dev_id, 1, struct.pack("<HHH", r, g, b), seq)


if __name__ == "__main__":
    # CRC-16/XMODEM standard check value.
    assert crc16_xmodem(b"123456789") == 0x31C3
    dev = int(sys.argv[1], 0) if len(sys.argv) > 1 else 1
    print(rgb_set(dev, 255, 0, 0).hex(" "))
