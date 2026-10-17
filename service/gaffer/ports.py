"""Getting a port to serve on, even when the usual one is taken.

The studio prefers 8787. When something else already listens there, it walks
up to the next free port, and past that lets the operating system choose. It
binds the port itself and hands the socket to the web server, so there is no
gap between "this port is free" and "this port is ours" for anything to slip into.
"""

from __future__ import annotations

import socket
import sys

DEFAULT_PORT = 8787


def _bind(host: str, port: int) -> socket.socket | None:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        if sys.platform == "win32":
            # Without this, Windows lets a second program bind a port already in use.
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)  # type: ignore[attr-defined]
        else:
            # Lets a restart reuse the port at once instead of waiting out TIME_WAIT.
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
    except OSError:
        sock.close()
        return None
    return sock


def bind_free_port(host: str, preferred: int = DEFAULT_PORT, tries: int = 20) -> tuple[socket.socket, int]:
    """A socket bound on ``host``: the preferred port if free, else the next free one, else any."""
    for port in range(preferred, preferred + max(1, tries)):
        if 0 < port < 65536:
            sock = _bind(host, port)
            if sock is not None:
                return sock, port
    sock = _bind(host, 0)
    if sock is None:
        raise OSError(f"no free port on {host}")
    return sock, sock.getsockname()[1]
