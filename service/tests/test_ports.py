"""Finding a free port, and telling launchers where a running studio is."""

from __future__ import annotations

import os
import socket

from gaffer.paths import clear_runtime, read_runtime, write_runtime
from gaffer.ports import bind_free_port


def _occupy(port: int) -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", port))
    s.listen()
    return s


def test_the_preferred_port_is_used_when_free():
    probe = _occupy(0)
    free = probe.getsockname()[1]
    probe.close()
    sock, port = bind_free_port("127.0.0.1", free)
    try:
        assert port == free
    finally:
        sock.close()


def test_a_busy_port_moves_to_the_next_free_one():
    held = _occupy(0)
    busy = held.getsockname()[1]
    try:
        sock, port = bind_free_port("127.0.0.1", busy)
        try:
            assert port != busy
            assert sock.getsockname()[1] == port
        finally:
            sock.close()
    finally:
        held.close()


def test_when_every_nearby_port_is_busy_the_system_picks_one():
    held = [_occupy(0)]
    start = held[0].getsockname()[1]
    try:
        sock, port = bind_free_port("127.0.0.1", start, tries=1)
        try:
            assert port not in (start, 0)
        finally:
            sock.close()
    finally:
        for h in held:
            h.close()


def test_launchers_can_find_a_running_studio(tmp_path):
    assert read_runtime(tmp_path) is None
    write_runtime(tmp_path, port=8790, url="http://127.0.0.1:8790/")
    info = read_runtime(tmp_path)
    assert info is not None and info["port"] == 8790 and info["pid"] == os.getpid()
    clear_runtime(tmp_path)
    assert read_runtime(tmp_path) is None


def test_a_damaged_runtime_file_reads_as_not_running(tmp_path):
    (tmp_path / "studio.json").write_text("{half", encoding="utf-8")
    assert read_runtime(tmp_path) is None
