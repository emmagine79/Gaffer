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

Phone access comes later, with a PIN (SPEC-015). Until then this is loopback only.
"""

from __future__ import annotations

import hmac
import json
import os
from pathlib import Path

from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import HTTPConnection, Request
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

COOKIE = "gaffer_session"
LOCAL_HOSTS = ["127.0.0.1", "localhost"]


def _refuse(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": code, "message": message})


class SessionGate:
    """ASGI middleware: /session signs the window in once; everything else needs the cookie."""

    def __init__(self, app: ASGIApp, secret: str) -> None:
        self.app = app
        self.secret = secret
        self.link_used = False

    def _matches(self, value: str | None) -> bool:
        return bool(value) and hmac.compare_digest(value.encode(), self.secret.encode())

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "websocket":
            # A socket is refused before it is accepted: the browser sees a failed handshake.
            if not self._matches(HTTPConnection(scope).cookies.get(COOKIE)):
                await receive()  # websocket.connect
                await send({"type": "websocket.close", "code": 4401})
                return
            await self.app(scope, receive, send)
            return
        if scope["type"] != "http":
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
        await self.app(scope, receive, send)


def protect(app: ASGIApp, secret: str) -> ASGIApp:
    """Wrap the app: the Host check runs first, then the session check."""
    return TrustedHostMiddleware(SessionGate(app, secret), allowed_hosts=LOCAL_HOSTS)


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
