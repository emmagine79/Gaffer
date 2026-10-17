"""Who may use the light service.

The service listens on 127.0.0.1, which keeps other machines out but not web
pages open in a browser on this Mac. Two checks close that:

* Host. A page on a domain that resolves to 127.0.0.1 (DNS rebinding) still sends
  its own name as the Host header, so only 127.0.0.1 and localhost are served
  (Starlette's TrustedHostMiddleware, which ignores the port).
* Session secret. Gaffer makes a random secret at each launch and hands it to the
  service on stdin. Its window opens /session?key=<secret> once; that sets the
  secret as an HttpOnly, SameSite=Strict cookie and the link stops working. Every
  other route, and the /ws socket that drives the lights, needs the cookie, so another
  site's page can't use the API even through 127.0.0.1.
* Origin. On top of the cookie, lumen-studio's guard.py (kept as is) makes /ws accept
  only the studio's own page.

Phone access (SPEC-015, phone.py) adds a second kind of caller. A request is the Mac window's
own only when it comes from this Mac AND names this Mac (127.0.0.1 or localhost) in its Host
header, and carries no forwarding header. A proxy on this Mac connects from loopback for visitors
who are not on it, so a loopback connection is never a phone (SPEC-024): with another Host it is
refused as ``network_not_allowed`` once phone access is on, and as a bad Host while it is off.
A proxy that sends no forwarding header we list and rewrites Host to 127.0.0.1 looks like the Mac
window; the launch secret cookie is what stops it.
Everything else is a phone: it is refused while phone access is off, its Host must be
one of the addresses phone access listed, and it needs the cookie that the right PIN earns
instead of the launch secret. The launch secret never goes to a phone, and a phone's cookie is
worth nothing to the Mac-only routes.
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import os
from pathlib import Path

from starlette.requests import HTTPConnection, Request
from starlette.responses import JSONResponse, PlainTextResponse, RedirectResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .guard import has_forwarding_headers, hostname, is_loopback_client, is_phone_source
from .phone import PHONE_COOKIE, PhoneAccess

COOKIE = "gaffer_session"
LOCAL_HOSTS = ["127.0.0.1", "localhost"]

#: What a phone that has not entered the PIN may fetch: the page itself, which then shows the PIN
#: screen (the page is open source, so it holds nothing secret), and the two sign-in routes.
_OPEN_TO_PHONES_GET = frozenset({"/", "/favicon.svg", "/api/session"})
_OPEN_TO_PHONES_POST = frozenset({"/api/session"})


def _refuse(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": code, "message": message})


class SessionGate:
    """ASGI middleware: /session signs the Mac window in once; a phone signs in with the PIN."""

    def __init__(self, app: ASGIApp, secret: str, phone: PhoneAccess | None = None) -> None:
        self.app = app
        self.secret = secret
        self.phone = phone
        self.link_used = False

    def _matches(self, value: str | None) -> bool:
        return bool(value) and hmac.compare_digest(value.encode(), self.secret.encode())

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        conn = HTTPConnection(scope)
        host = hostname(conn.headers.get("host") or "")
        client = scope.get("client")
        loopback = is_loopback_client(client[0] if client else None)
        phone = self.phone
        if loopback and has_forwarding_headers(conn.headers.keys()):
            # A proxy on this Mac (tailscale serve, ssh -L, a dev proxy) is passing on someone who may be anywhere.
            # Only a direct connection is the Mac window; a phone does not come through loopback (SPEC-024).
            await self._deny(scope, receive, send, _refuse(
                403, "network_not_allowed", "Gaffer does not answer requests forwarded by a proxy on this Mac."), 4403)
        elif host in LOCAL_HOSTS and loopback:
            await self._mac_window(scope, receive, send, conn)
        elif phone is None or not phone.enabled:
            # A foreign Host from this Mac is a web page trying DNS rebinding; from elsewhere it is a phone
            # while phone access is off.
            if loopback or phone is None:
                await self._deny(scope, receive, send, PlainTextResponse("Invalid host header", status_code=400))
            else:
                await self._deny(scope, receive, send, _refuse(
                    403, "phone_access_off", "Phone access is off. Switch it on in Gaffer on the Mac."), 4403)
        elif not is_phone_source(client[0] if client else None):
            await self._deny(scope, receive, send, _refuse(
                403, "network_not_allowed", "Gaffer only answers a phone on the same Wi-Fi network as the Mac, or on Tailscale."), 4403)
        elif host not in phone.hosts():
            await self._deny(scope, receive, send, PlainTextResponse("Invalid host header", status_code=400), 4403)
        else:
            await self._phone(scope, receive, send, conn, phone)

    @staticmethod
    async def _deny(scope: Scope, receive: Receive, send: Send, response: Response, ws_code: int = 4403) -> None:
        if scope["type"] == "websocket":
            await receive()  # websocket.connect; the browser sees a failed handshake
            await send({"type": "websocket.close", "code": ws_code})
        else:
            await response(scope, receive, send)

    async def _mac_window(self, scope: Scope, receive: Receive, send: Send, conn: HTTPConnection) -> None:
        scope["gaffer_local"] = True
        if scope["type"] == "websocket":
            # A socket is refused before it is accepted: the browser sees a failed handshake.
            if not self._matches(conn.cookies.get(COOKIE)):
                await receive()  # websocket.connect
                await send({"type": "websocket.close", "code": 4401})
                return
            scope["gaffer_signed_in"] = True
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        response: Response | None = None
        if scope["path"] == "/session":
            if self.link_used or not self._matches(request.query_params.get("key")):
                response = _refuse(401, "link_not_valid", "This sign-in link is not valid. Open Gaffer from the menu bar.")
            else:
                self.link_used = True
                response = RedirectResponse("/", status_code=303)
                response.set_cookie(COOKIE, self.secret, httponly=True, samesite="strict", path="/")
        elif not self._matches(request.cookies.get(COOKIE)):
            response = _refuse(401, "not_signed_in", "Open Gaffer from the menu bar to use it.")
        if response is not None:
            await response(scope, receive, send)
            return
        scope["gaffer_signed_in"] = True
        await self.app(scope, receive, send)

    async def _phone(self, scope: Scope, receive: Receive, send: Send, conn: HTTPConnection, phone: PhoneAccess) -> None:
        scope["gaffer_local"] = False
        token = conn.cookies.get(PHONE_COOKIE)
        signed_out = phone.session(token)  # None: this browser has not entered the PIN
        signed_in = signed_out is not None
        scope["gaffer_signed_in"] = signed_in
        if scope["type"] == "websocket":
            if signed_out is None:
                await self._deny(scope, receive, send, _refuse(401, "pin_required", "Enter the PIN."), 4401)
                return
            await self._socket_until_signed_out(scope, receive, send, signed_out)
            return
        if signed_in:
            await self.app(scope, receive, send)
            return
        path, method = scope["path"], scope["method"]
        if (method == "GET" and (path in _OPEN_TO_PHONES_GET or path.startswith("/assets/"))) or (
                method == "POST" and path in _OPEN_TO_PHONES_POST):
            await self.app(scope, receive, _page_is_401(path, send))
            return
        await _refuse(401, "pin_required", "Enter the PIN shown on the Mac.")(scope, receive, send)

    async def _socket_until_signed_out(self, scope: Scope, receive: Receive, send: Send, ended: asyncio.Event) -> None:
        """Run the light socket, and end it the moment New PIN or switching off signs this phone out."""
        running = asyncio.create_task(self.app(scope, receive, send))
        signed_out = asyncio.create_task(ended.wait())
        try:
            await asyncio.wait({running, signed_out}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            signed_out.cancel()
            if not running.done():
                running.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await running
                with contextlib.suppress(Exception):
                    await send({"type": "websocket.close", "code": 4401})
        if running.done() and not running.cancelled():
            running.result()  # raises whatever ended the socket abnormally


def _page_is_401(path: str, send: Send) -> Send:
    """The page a phone gets before the PIN is sent with status 401, so nothing mistakes it for a signed-in page."""

    async def wrapped(message: Message) -> None:
        if message["type"] == "http.response.start" and message["status"] == 200 and not path.startswith("/assets/"):
            headers = {k.lower(): v for k, v in message.get("headers", [])}
            if headers.get(b"content-type", b"").startswith(b"text/html"):
                message = {**message, "status": 401}
        await send(message)

    return wrapped


def protect(app: ASGIApp, secret: str, phone: PhoneAccess | None = None) -> ASGIApp:
    """Wrap the app: the Host check runs first, then the session check."""
    return SessionGate(app, secret, phone)


def runtime_file(pid: int) -> Path:
    """Where a running service records its port and secret for local tools (mode 0600)."""
    return Path.home() / "Library" / "Application Support" / "Gaffer" / "run" / f"service-{pid}.json"


def write_runtime_file(port: int, secret: str) -> Path:
    path = runtime_file(os.getpid())
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"pid": os.getpid(), "port": port, "secret": secret}, f)
    return path
