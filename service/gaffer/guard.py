"""Who may talk to the studio. Pure.

The studio listens on 127.0.0.1, which keeps other machines out but not other
web pages: any site open in the same browser can open a WebSocket to
``ws://127.0.0.1:8787`` and, unchecked, drive the lights or pair one with a
device it controls. Two checks close that:

* **Origin.** A browser always says which page opened a WebSocket. Only the
  studio's own page is accepted. A program with no Origin header is not a web
  page; it already runs on this computer and can read the keys directly.
* **Host.** A page on a domain that resolves to 127.0.0.1 (DNS rebinding) still
  sends its own name as the Host header, so only this machine's names, and the
  LAN address when ``--lan`` is on, are served.
"""

from __future__ import annotations

from urllib.parse import urlsplit

LOCAL_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "localhost", "::1", "testserver"})
LOOPBACK: frozenset[str] = frozenset({"127.0.0.1", "::1", "localhost", "testclient"})


def hostname(host_header: str) -> str:
    """The name in a Host header, without its port; IPv6 brackets removed."""
    host = host_header.strip().lower()
    if host.startswith("["):
        return host[1:host.find("]")] if "]" in host else host[1:]
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


def host_allowed(host_header: str | None, allowed: frozenset[str]) -> bool:
    return bool(host_header) and hostname(host_header or "") in allowed


def origin_allowed(origin: str | None, host_header: str | None, allowed: frozenset[str]) -> bool:
    """Whether a WebSocket's opener is the studio's own page (or not a browser at all)."""
    if origin is None:
        return True
    if not host_allowed(host_header, allowed):
        return False
    parts = urlsplit(origin)
    return parts.scheme in ("http", "https") and parts.netloc.lower() == (host_header or "").strip().lower()
