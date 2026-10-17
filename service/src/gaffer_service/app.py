"""Gaffer's light service: the HTTP API and the web page the Mac window shows."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from importlib.resources import files
from typing import Any

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse

from .scan import DEFAULT_SCAN_SECONDS, MAX_SCAN_SECONDS, MIN_SCAN_SECONDS, Scanner

log = logging.getLogger("gaffer.app")

# CBManagerAuthorization values (Apple CoreBluetooth): 0 not determined, 1 restricted, 2 denied, 3 allowed always.
_PERMISSION = {0: "not_determined", 1: "restricted", 2: "denied", 3: "allowed"}

# Plain-words answers for each way Bluetooth can be unavailable. Never include paths or raw errors.
_BLUETOOTH_ERRORS = {
    "DENIED_BY_USER": (403, "bluetooth_denied", "Gaffer isn't allowed to use Bluetooth. Turn it on in System Settings, Privacy & Security, Bluetooth."),
    "DENIED_BY_SYSTEM": (403, "bluetooth_restricted", "Bluetooth is blocked on this Mac by a restriction. Ask whoever manages the Mac."),
    "DENIED_BY_UNKNOWN": (403, "bluetooth_denied", "Gaffer isn't allowed to use Bluetooth. Turn it on in System Settings, Privacy & Security, Bluetooth."),
    "POWERED_OFF": (503, "bluetooth_off", "Bluetooth is turned off. Turn it on in Control Centre and scan again."),
    "NO_BLUETOOTH": (503, "no_bluetooth", "This Mac has no Bluetooth."),
}
_BLUETOOTH_UNAVAILABLE = (503, "bluetooth_unavailable", "Bluetooth isn't ready. Wait a moment and scan again.")


def bluetooth_permission() -> str:
    """Whether macOS lets this app use Bluetooth. Reading it never shows the prompt."""
    from CoreBluetooth import CBManager

    return _PERMISSION.get(int(CBManager.authorization()), "unknown")


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": code, "message": message})


def create_app(on_shutdown: Callable[[], None] | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        if on_shutdown is not None:
            on_shutdown()

    app = FastAPI(title="Gaffer light service", docs_url=None, redoc_url=None, lifespan=lifespan)
    scanner = Scanner()
    page = files("gaffer_service").joinpath("static/index.html").read_text(encoding="utf-8")

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return page

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "service": "gaffer"}

    @app.get("/api/bluetooth")
    async def bluetooth() -> dict[str, Any]:
        return {"permission": bluetooth_permission()}

    @app.get("/api/scan")
    async def scan(seconds: float = Query(DEFAULT_SCAN_SECONDS)) -> Any:
        seconds = max(MIN_SCAN_SECONDS, min(MAX_SCAN_SECONDS, seconds))
        from bleak.exc import BleakBluetoothNotAvailableError

        try:
            result = await scanner.scan(seconds)
        except BleakBluetoothNotAvailableError as err:
            reason = getattr(getattr(err, "reason", None), "name", "")
            log.warning("bluetooth unavailable: %s (%r)", reason, err)
            return _error(*_BLUETOOTH_ERRORS.get(reason, _BLUETOOTH_UNAVAILABLE))
        except Exception:
            log.exception("scan failed")
            return _error(500, "scan_failed", "The scan failed. Try again.")
        result["permission"] = bluetooth_permission()
        return result

    return app
