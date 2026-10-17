"""The one place that builds a uvicorn config for the guarded app (SPEC-024).

uvicorn's default ``proxy_headers=True`` replaces the peer address with the one in X-Forwarded-For when the
connection comes from 127.0.0.1. The gate in session.py decides who a caller is from the real peer, so a
visitor behind a proxy on this Mac could pick the address the gate sees. Every listener for the guarded app
is built here, so none can get that default back.
"""

from __future__ import annotations

from typing import Any

import uvicorn
from starlette.types import ASGIApp


def guarded_config(app: ASGIApp, **options: Any) -> uvicorn.Config:
    """A uvicorn config that leaves the peer address as the connection's own. ``options`` go to uvicorn.Config."""
    return uvicorn.Config(app, **{**options, "proxy_headers": False})
