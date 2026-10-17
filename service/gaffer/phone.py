"""Phone access: a QR code, a PIN, and Tailscale (SPEC-015).

The service listens on 127.0.0.1 and nothing else until the Mac's owner switches phone
access on. Then it also listens on the Wi-Fi, and a phone gets in like this:

1. The phone scans the QR code on the Mac, which holds only the address (no secret).
2. The phone shows a PIN screen. The owner types the PIN the Mac shows.
3. Right PIN: the service sets an HttpOnly cookie and the phone can control the lights.
4. Wrong PIN: refused. After MAX_WRONG_GUESSES wrong ones the PIN stops working until the
   owner presses New PIN on the Mac.

This module holds the state and the pure parts. The checks that stand in front of every route
and the light socket are in session.py. The Mac window talks to this module through the
routes in ``phone_routes`` (Mac only: a phone can never read the PIN or switch access off).
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import ipaddress
import json
import logging
import os
import re
import secrets
import shutil
import socket
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import segno
import uvicorn
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp

from .guard import origin_allowed
from .listener import guarded_config

logger = logging.getLogger(__name__)

#: Cookie a phone gets after the right PIN. A random token, not the Mac window's secret.
PHONE_COOKIE = "gaffer_phone"

#: Digits in the PIN. Conductor default recorded on the card (SPEC-015) for Captain to change.
PIN_DIGITS = 6

#: Wrong guesses a PIN survives. Authority: NIST SP 800-63B section 5.2.2, "limit consecutive
#: failed authentication attempts ... to no more than 100". Counted per PIN and never reset by a
#: right guess, which keeps it at or under that ceiling. Not per phone: an attacker with several
#: addresses shares the one budget.
MAX_WRONG_GUESSES = 100

#: Longest sign-in body read. Derived from the contract: the body is {"pin": "NNNNNN"}, 17 bytes
#: with Python's json.dumps spacing; 64 leaves room for other clients' spacing. A longer body
#: is not a PIN attempt, so it is refused without being read to the end or counted.
MAX_PIN_BODY_BYTES = 64

#: A DNS name is at most 253 characters (RFC 1035 section 2.3.4).
_MAX_DNS_NAME = 253
_DNS_NAME = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*$")

#: Where the Tailscale app keeps its command line tool when it is not on PATH.
TAILSCALE_APP_CLI = "/Applications/Tailscale.app/Contents/MacOS/Tailscale"


class TailscaleUnreadable(Exception):
    """`tailscale status` did not give an answer (it would not start, failed, or printed nonsense).
    That says nothing about whether Tailscale is running, so an earlier good answer stays."""


class PhoneUnavailable(Exception):
    """Phone access could not be switched on. The message is plain words, safe to show."""


# --- the addresses a phone can reach -------------------------------------------------------------


def default_lan_ip() -> str | None:
    """This Mac's Wi-Fi or Ethernet address, or None when it has no network.

    Connecting a UDP socket sends nothing; it only asks the system which address it would
    use to reach a far-away host (192.0.2.1 is the documentation range, RFC 5737).
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))
        address = probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()
    return None if address.startswith("127.") or address == "0.0.0.0" else address


@dataclass(frozen=True)
class TailscaleInfo:
    """What `tailscale status --json` says about this Mac."""

    ips: tuple[str, ...]
    name: str | None  # the MagicDNS name, without the trailing dot


def parse_tailscale(raw: str) -> TailscaleInfo | None:
    """Read `tailscale status --json`.

    Returns None when the tool positively says Tailscale is not running. Raises TailscaleUnreadable
    when the output is not a status at all.
    """
    try:
        status = json.loads(raw)
        me = status["Self"]
        running = status.get("BackendState") == "Running"
        ips: list[str] = []
        for text in me.get("TailscaleIPs") or []:
            ips.append(ipaddress.ip_address(text).compressed)
        name = str(me.get("DNSName") or "").rstrip(".").lower()
    except (ValueError, KeyError, TypeError, AttributeError) as err:
        raise TailscaleUnreadable("not a Tailscale status") from err
    if not running:
        return None
    if not _DNS_NAME.match(name) or len(name) > _MAX_DNS_NAME:
        name = ""
    if not ips and not name:
        raise TailscaleUnreadable("Tailscale is running but lists no address")
    return TailscaleInfo(tuple(ips), name or None)


def find_tailscale_cli() -> str | None:
    for candidate in (shutil.which("tailscale"), TAILSCALE_APP_CLI):
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


async def read_tailscale(cli: str | None) -> TailscaleInfo | None:
    """Run `tailscale status --json`. None means Tailscale is not installed or not running.

    Raises TailscaleUnreadable when the tool is there but gives no answer.
    """
    if cli is None:
        return None
    try:
        process = await asyncio.create_subprocess_exec(
            cli, "status", "--json", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            stdin=asyncio.subprocess.DEVNULL)
    except OSError as err:
        raise TailscaleUnreadable("could not start the tailscale tool") from err
    try:
        out, _ = await process.communicate()
    except BaseException:
        process.kill()  # cancelled (access switched off, the panel opened again, or the service stopping)
        await process.wait()
        raise
    if process.returncode != 0:
        raise TailscaleUnreadable(f"tailscale exited with {process.returncode}")
    return parse_tailscale(out.decode("utf-8", "replace"))


def qr_data_uri(url: str) -> str:
    """A QR code of the URL as an SVG data URI, with the 4-module quiet zone the QR standard asks for."""
    return segno.make(url, error="m").svg_data_uri(scale=6, border=4, dark="#000000", light="#ffffff")


# --- the second listener -------------------------------------------------------------------------


class PhoneListener:
    """The service's app, also served on every network address at the same port.

    A second uvicorn server shares the event loop and the app; the app's start-up and
    shut-down belong to the first server (``lifespan="off"`` here). Its own signal handling
    is not used (``serve()`` would replace the first server's).
    """

    def __init__(self, app: ASGIApp, port: int, graceful_seconds: float) -> None:
        self.app, self.port, self.graceful_seconds = app, port, graceful_seconds
        self.server: uvicorn.Server | None = None
        self.sock: socket.socket | None = None
        self.task: asyncio.Task[None] | None = None

    def _bind(self) -> socket.socket:
        """Listen on every network address, IPv6 and IPv4 together (a phone may resolve the Tailscale
        name to either). A Mac with no IPv6 falls back to IPv4 alone."""
        failure: OSError | None = None
        for family, address in ((socket.AF_INET6, "::"), (socket.AF_INET, "0.0.0.0")):
            try:
                sock = socket.socket(family, socket.SOCK_STREAM)
            except OSError as err:
                failure = err
                continue
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                if family == socket.AF_INET6:
                    sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
                sock.bind((address, self.port))
                sock.listen()
                return sock
            except OSError as err:
                sock.close()
                failure = err
        assert failure is not None
        raise failure

    async def start(self) -> None:
        try:
            sock = self._bind()
        except OSError as err:
            logger.warning("phone listener could not bind port %s: %r", self.port, err)
            raise PhoneUnavailable("Gaffer could not open its port to the network. Try again.") from err
        try:
            config = guarded_config(self.app, lifespan="off", log_level="warning", access_log=False,
                                    timeout_graceful_shutdown=self.graceful_seconds)
            server = uvicorn.Server(config)
            config.load()
            server.lifespan = config.lifespan_class(config)
            await server.startup(sockets=[sock])  # uvicorn calls sys.exit when it cannot start
        except (Exception, SystemExit) as err:
            sock.close()
            logger.warning("phone listener could not start on port %s: %r", self.port, err)
            raise PhoneUnavailable("Gaffer could not open its port to the network. Try again.") from err
        self.server, self.sock = server, sock
        self.task = asyncio.create_task(server.main_loop())

    async def stop(self) -> None:
        server, sock, task = self.server, self.sock, self.task
        self.server = self.sock = self.task = None
        if server is None or task is None:
            return
        server.should_exit = True
        await task
        await server.shutdown(sockets=[sock] if sock else None)
        if sock is not None:
            sock.close()


# --- the state -----------------------------------------------------------------------------------


def saved_port(saved: Path) -> int | None:
    """The port phone access used last time, if it was left on, so phones keep the same address."""
    try:
        data = json.loads(saved.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    port = data.get("port") if isinstance(data, dict) and data.get("enabled") is True else None
    return port if isinstance(port, int) and not isinstance(port, bool) and 0 < port < 65536 else None


class PhoneAccess:
    """Whether phones may connect, the PIN, and who has entered it."""

    def __init__(
        self,
        *,
        port: int,
        lan_ip: Callable[[], str | None] = default_lan_ip,
        tailscale_cli: Callable[[], str | None] = find_tailscale_cli,
        saved: Path | None = None,
    ) -> None:
        self.port = port
        #: Where phone access and its PIN are kept, so a restart leaves them as they were (Captain,
        #: 18 Oct 2026). None keeps them in memory only.
        self._saved = saved
        self._lan_ip, self._tailscale_cli = lan_ip, tailscale_cli
        self.enabled = False
        self.pin: str | None = None
        self.wrong = 0
        self._sessions: dict[str, asyncio.Event] = {}
        self._hosts: frozenset[str] = frozenset()
        self._targets: list[dict[str, str]] = []
        self._lan: str | None = None
        self._tailscale: TailscaleInfo | None = None
        self._tailscale_known = False  # False until the first `tailscale status` has ended
        self._check: asyncio.Task[None] | None = None
        self._waiters: set[asyncio.Future[None]] = set()
        self._lock: asyncio.Lock | None = None
        self._listener_args: tuple[ASGIApp, float] | None = None
        self._listener: PhoneListener | None = None

    # what the checks in front of the app read
    def hosts(self) -> frozenset[str]:
        """The names and addresses a phone may use in its Host header. Empty while access is off."""
        return self._hosts if self.enabled else frozenset()

    @property
    def locked(self) -> bool:
        return self.enabled and self.wrong >= MAX_WRONG_GUESSES

    def session(self, token: str | None) -> asyncio.Event | None:
        """This phone's sign-in, or None when it has none. The event is set when the sign-in ends
        (New PIN, or access switched off)."""
        return self._sessions.get(token) if self.enabled and token is not None else None

    # the PIN
    def check_pin(self, candidate: object) -> str:
        """"ok", "wrong", "locked", "off" or "malformed". Runs without awaiting, so guesses are counted one at a time."""
        if not self.enabled or self.pin is None:
            return "off"
        if not (isinstance(candidate, str) and len(candidate) == PIN_DIGITS and candidate.isascii() and candidate.isdigit()):
            return "malformed"  # cannot be the PIN, so it narrows nothing and is not counted
        if self.wrong >= MAX_WRONG_GUESSES:
            return "locked"
        if hmac.compare_digest(candidate.encode(), self.pin.encode()):
            return "ok"
        self.wrong += 1
        return "locked" if self.wrong >= MAX_WRONG_GUESSES else "wrong"

    def sign_in(self) -> str:
        token = secrets.token_urlsafe(32)
        self._sessions[token] = asyncio.Event()
        return token

    def _new_pin(self) -> None:
        self.pin = "".join(secrets.choice("0123456789") for _ in range(PIN_DIGITS))
        self.wrong = 0
        self._sign_everyone_out()

    def _sign_everyone_out(self) -> None:
        sessions, self._sessions = self._sessions, {}
        for ended in sessions.values():
            ended.set()

    # switching on and off
    def bind_listener(self, app: ASGIApp, graceful_seconds: float) -> None:
        """Serve ``app`` on the network when access is on. Without this call nothing opens a socket."""
        self._listener_args = (app, graceful_seconds)

    def _guard(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def _refresh_addresses(self) -> None:
        """Work out the Wi-Fi address (a local lookup, no process) and the names and addresses a phone may use."""
        self._lan = lan = self._lan_ip()
        found = self._tailscale
        hosts: set[str] = set()
        targets: list[dict[str, str]] = []
        if lan:
            hosts.add(lan)
            targets.append({"kind": "wifi", "label": "Same Wi-Fi", "url": f"http://{lan}:{self.port}/"})
        if found:
            hosts.update(found.ips)
            if found.name:
                hosts.add(found.name)
            v4 = next((ip for ip in found.ips if "." in ip), None)
            where = found.name or v4
            if where:
                targets.append({"kind": "tailscale", "label": "Away, over Tailscale", "url": f"http://{where}:{self.port}/"})
        self._hosts = frozenset(hosts)
        self._targets = targets

    @property
    def checking(self) -> bool:
        """Whether `tailscale status` is still running. Nothing waits for it: it ends when it answers
        or when access is switched off, which kills it."""
        return self.enabled and self._check is not None and not self._check.done()

    def refresh(self) -> None:
        """Start a new Tailscale check, ending one that is still running (it may be stuck). Returns at once.

        The last good answer stays in use until a check gives a better one, so a stuck or failing
        tool never takes the Tailscale names away from a phone that is already connected.
        """
        if not self.enabled:
            return
        if self._check is not None:
            self._check.cancel()  # kills the tool; waiters on ?wait=1 move on to the new check
        self._check = asyncio.create_task(self._check_tailscale())
        self._check.add_done_callback(self._release_waiters)

    async def _check_tailscale(self) -> None:
        try:
            found = await read_tailscale(self._tailscale_cli())
        except TailscaleUnreadable as err:
            logger.warning("tailscale gave no answer: %s", err)
            if self.enabled:
                self._tailscale_known = True  # with nothing good to keep, report "not found" until a check succeeds
            return
        if self.enabled:
            self._tailscale, self._tailscale_known = found, True
            self._refresh_addresses()

    def _release_waiters(self, _task: object = None) -> None:
        for waiter in self._waiters:
            if not waiter.done():
                waiter.set_result(None)

    async def settled(self) -> None:
        """Return when no Tailscale check is running (at once if none is)."""
        while self.checking:
            waiter: asyncio.Future[None] = asyncio.get_running_loop().create_future()
            self._waiters.add(waiter)
            try:
                await waiter
            finally:
                self._waiters.discard(waiter)

    def _save(self) -> None:
        """Write whether access is on and its PIN, readable by this user only."""
        if self._saved is None:
            return
        data = json.dumps({"enabled": self.enabled, "pin": self.pin if self.enabled else None, "port": self.port})
        tmp = self._saved.with_name(self._saved.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(data)
        os.replace(tmp, self._saved)

    def _save_or_warn(self) -> bool:
        try:
            self._save()
            return True
        except OSError:
            logger.warning("phone access settings could not be saved", exc_info=True)
            return False

    async def restore(self) -> None:
        """Switch access back on with its old PIN if it was on when Gaffer last stopped."""
        if self._saved is None:
            return
        try:
            saved = json.loads(self._saved.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError):
            logger.warning("phone access settings could not be read; phone access stays off")
            return
        pin = saved.get("pin") if isinstance(saved, dict) and saved.get("enabled") is True else None
        if isinstance(pin, str) and len(pin) == PIN_DIGITS and pin.isascii() and pin.isdigit():
            try:
                await self.enable(pin=pin)
            except (PhoneUnavailable, OSError):
                # The lights matter more than the phone: Gaffer starts, with phone access off for now.
                logger.warning("phone access could not be switched back on at start; it stays off", exc_info=True)

    async def enable(self, *, pin: str | None = None) -> None:
        async with self._guard():
            if self.enabled:
                return
            self._refresh_addresses()  # an earlier good Tailscale answer is kept; the check below renews it
            if self._listener_args is not None:
                listener = PhoneListener(self._listener_args[0], self.port, self._listener_args[1])
                await listener.start()
                self._listener = listener
            if pin is None:
                self._new_pin()
            else:
                self.pin, self.wrong = pin, 0
            self.enabled = True
            self._save_or_warn()
            self.refresh()  # the Tailscale names join the allowed set when the tool answers

    async def disable(self, *, save: bool = True) -> None:
        """Switch access off. ``save=False`` (Gaffer quitting) closes it now but leaves it on for the next start."""
        async with self._guard():
            try:
                await self._close()
            finally:
                if save and not self._save_or_warn() and self._saved is not None:
                    with contextlib.suppress(OSError):
                        self._saved.unlink()  # never left saying "on" once switched off

    async def _close(self) -> None:
        """Turn access off now: forget the PIN, sign every phone out, close the listener."""
        self.enabled = False
        self.pin = None
        self._sign_everyone_out()
        self._hosts, self._targets = frozenset(), []
        check, self._check = self._check, None
        if check is not None:
            check.cancel()  # kills a `tailscale` that is still running
            await asyncio.gather(check, return_exceptions=True)
        listener, self._listener = self._listener, None
        if listener is not None:
            await listener.stop()

    async def new_pin(self) -> None:
        async with self._guard():
            if self.enabled:
                self._new_pin()
                self._save_or_warn()

    def status(self) -> dict[str, Any]:
        """What the Mac window shows. Only ever sent to the Mac itself: it holds the PIN."""
        if self.enabled:
            self._refresh_addresses()  # the Wi-Fi address may have changed since last time
        return {
            "enabled": self.enabled,
            "pin": self.pin if self.enabled else None,
            "locked": self.locked,
            "checking": self.checking,
            "tailscale": (self._tailscale is not None) if self.enabled and self._tailscale_known else None,
            "targets": [{**t, "qr": qr_data_uri(t["url"])} for t in self._targets] if self.enabled else [],
        }


# --- routes --------------------------------------------------------------------------------------


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": code, "message": message})


def phone_routes(phone: PhoneAccess, allowed_hosts: Callable[[], frozenset[str]]) -> APIRouter:
    """The sign-in routes (any phone) and the Mac-only routes that switch phone access on and off."""
    router = APIRouter()

    def mac_only(request: Request) -> JSONResponse | None:
        # The gate in session.py marks a request "local" only for the Mac window's own connection.
        if request.scope.get("gaffer_local") is not True:
            return _error(403, "mac_only", "Phone access is changed on the Mac, not on a phone.")
        # Another page open on this Mac must not flip it, even though the cookie would be sent.
        if not origin_allowed(request.headers.get("origin"), request.headers.get("host"), allowed_hosts()):
            return _error(403, "wrong_origin", "That request did not come from the Gaffer window.")
        return None

    @router.get("/api/session")
    async def session_state(request: Request) -> JSONResponse:
        """Is this browser signed in? The page asks first, then shows the PIN screen or the studio."""
        if request.scope.get("gaffer_signed_in") is True:
            return JSONResponse({"signed_in": True, "local": request.scope.get("gaffer_local") is True})
        return _error(401, "pin_required", "Enter the PIN shown on the Mac.")

    @router.post("/api/session")
    async def sign_in(request: Request) -> JSONResponse:
        if request.scope.get("gaffer_local") is True:
            return JSONResponse({"ok": True})  # the Mac window needs no PIN
        body = b""
        async for chunk in request.stream():
            body += chunk
            if len(body) > MAX_PIN_BODY_BYTES:
                return _error(400, "bad_pin", f"Enter the {PIN_DIGITS}-digit PIN shown on the Mac.")
        try:
            pin = json.loads(body or b"null")["pin"]
        except (ValueError, KeyError, TypeError):
            pin = None
        result = phone.check_pin(pin)
        if result == "ok":
            reply = JSONResponse({"ok": True})
            # A session cookie, as the Mac window's (SPEC-002): no lifetime of its own, and it ends when
            # New PIN or switching off signs the phone out. Not Secure: the Wi-Fi address is plain http.
            reply.set_cookie(PHONE_COOKIE, phone.sign_in(), httponly=True, samesite="strict", path="/")
            return reply
        if result == "wrong":
            return _error(401, "wrong_pin", "That PIN is not right. Check the PIN on the Mac.")
        if result == "locked":
            return _error(403, "pin_locked", "Too many wrong PINs. Press New PIN on the Mac and try again.")
        if result == "off":
            return _error(403, "phone_access_off", "Phone access is off. Switch it on in Gaffer on the Mac.")
        return _error(400, "bad_pin", f"Enter the {PIN_DIGITS}-digit PIN shown on the Mac.")

    @router.get("/api/phone")
    async def phone_state(request: Request) -> JSONResponse:
        refused = mac_only(request)
        if refused:
            return refused
        if request.query_params.get("wait"):
            await phone.settled()  # the window holds this request open until Tailscale has answered
        else:
            phone.refresh()  # opening the panel looks again, in the background
        return JSONResponse(phone.status())

    @router.post("/api/phone")
    async def phone_switch(request: Request) -> JSONResponse:
        refused = mac_only(request)
        if refused:
            return refused
        try:
            wanted = (await request.json())["enabled"]
        except (ValueError, KeyError, TypeError):
            wanted = None
        if not isinstance(wanted, bool):
            return _error(400, "bad_request", 'Send {"enabled": true} or {"enabled": false}.')
        try:
            await (phone.enable() if wanted else phone.disable())
        except PhoneUnavailable as err:
            return _error(503, "phone_unavailable", str(err))
        return JSONResponse(phone.status())

    @router.post("/api/phone/pin")
    async def phone_new_pin(request: Request) -> JSONResponse:
        refused = mac_only(request)
        if refused:
            return refused
        await phone.new_pin()
        return JSONResponse(phone.status())

    return router

