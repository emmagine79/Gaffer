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

import ipaddress
from collections.abc import Iterable
from urllib.parse import urlsplit

LOCAL_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "localhost", "::1", "testserver"})
LOOPBACK: frozenset[str] = frozenset({"127.0.0.1", "::1", "localhost", "testclient"})


def is_loopback_client(address: str | None) -> bool:
    """Whether a connection comes from this Mac itself (its peer address, not a header).

    Anything else, including no address at all, is a phone or another machine.
    """
    if not address:
        return False
    if address in LOOPBACK:
        return True
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return (ip.ipv4_mapped or ip).is_loopback if ip.version == 6 else ip.is_loopback


#: Where a phone's connection may come from. Anything else (a public address) is refused before the PIN
#: is looked at, because a Host header is whatever the sender writes. Loopback is not here (SPEC-024): a
#: proxy on this Mac (`tailscale serve` or Funnel, `ssh -L`, a dev proxy) connects from 127.0.0.1 for a
#: visitor who could be anywhere, so loopback means the Mac window and nothing else. Each range has an
#: authority: private IPv4 (RFC 1918 section 3: 10/8, 172.16/12, 192.168/16); link-local (RFC 3927
#: section 2.1 for 169.254/16, RFC 4291 section 2.5.6 for fe80::/10); unique local IPv6 (RFC 4193
#: section 3, fc00::/7); Tailscale's addresses (100.64.0.0/10, the CGNAT range of RFC 6598, and
#: fd7a:115c:a1e0::/48, both from Tailscale's "IP and DNS addresses" documentation).
PHONE_SOURCES: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = tuple(ipaddress.ip_network(n) for n in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16",
    "fe80::/10", "fc00::/7", "100.64.0.0/10", "fd7a:115c:a1e0::/48"))

#: Headers a reverse proxy adds to say who it is forwarding for. Names are lower case, as Starlette gives them.
#: ``x-forwarded-*`` is the de facto set (X-Forwarded-For, -Host, -Proto), ``forwarded`` is RFC 7239, and
#: ``tailscale-*`` is what `tailscale serve` and Funnel add (Tailscale-User-Login and the like, from Tailscale's
#: "Tailscale Serve" documentation).
FORWARDING_PREFIXES: tuple[str, ...] = ("x-forwarded-", "tailscale-")
FORWARDING_NAMES: frozenset[str] = frozenset({"forwarded"})


def has_forwarding_headers(header_names: Iterable[str]) -> bool:
    """Whether a request carries any header that a reverse proxy sets to say it is passing someone else's request on."""
    return any(name.lower() in FORWARDING_NAMES or name.lower().startswith(FORWARDING_PREFIXES) for name in header_names)


def is_phone_source(address: str | None) -> bool:
    """Whether a connection's peer address is on this Mac's own network, a private one, or Tailscale.

    The v4 address inside an IPv4-mapped IPv6 address (``::ffff:192.168.1.5``, what a dual-stack
    listener reports) is the one that counts. No address, or one that does not parse, is refused.
    """
    if not address:
        return False
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return any(ip.version == net.version and ip in net for net in PHONE_SOURCES)


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
