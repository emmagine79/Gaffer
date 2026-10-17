"""HTTP and WebSocket surface."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
from collections.abc import Callable
from contextlib import asynccontextmanager
from importlib.resources import files
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import looks
from .commands import CommandError, dispatch
from .guard import LOCAL_HOSTS, LOOPBACK, host_allowed, origin_allowed
from .catalog import configure_models, models_catalog, skipped_model_files
from .hub import Client, Hub
from .lights import LightLibrary
from .scan import DEFAULT_SCAN_SECONDS, MAX_SCAN_SECONDS, MIN_SCAN_SECONDS, DemoScanner as DemoAdvertScanner, Scanner as AdvertScanner
from .store import Store

logger = logging.getLogger(__name__)

#: Commands that can take seconds (a scan, a pairing, a move to another network).
#: They run beside the socket's loop, so sliders keep working meanwhile, and
#: answer by request id when they finish.
LONG_RUNNING = frozenset({"lights.scan", "lights.pair", "lights.import", "select"})

# The built web page. A built Gaffer.app carries it inside this package (scripts/build_app.sh
# copies web/dist to gaffer/web); a source checkout serves web/dist from the repository root.
STUDIO_ROOT = Path(__file__).resolve().parents[2]
_BUNDLED_WEB = Path(__file__).resolve().parent / "web"
WEB_DIST = _BUNDLED_WEB if _BUNDLED_WEB.is_dir() else STUDIO_ROOT / "web" / "dist"

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


def create_app(
    *,
    demo: bool,
    data_dir: Path,
    token: str | None = None,
    scanner: Any = None,
    pairer: Any = None,
    fps: float = 60.0,
    hosts: tuple[str, ...] = (),
    advert_scanner: Any = None,
    on_shutdown: Callable[[], None] | None = None,
) -> FastAPI:
    """The studio app. ``hosts`` adds names it may be reached by.

    ``advert_scanner`` answers /api/scan (the Bluetooth scan that tags brand families); demo mode
    uses canned adverts so it never starts a Bluetooth scan. ``on_shutdown`` runs when the app stops.
    """
    allowed = LOCAL_HOSTS | frozenset(h.lower() for h in hosts)
    store = Store(data_dir)
    # Model files in <data>/models/<driver>/ join the shipped ones; demo mode adds its stand-ins.
    from .demo import DEMO_MODELS

    configure_models([Path(data_dir) / "models"], DEMO_MODELS if demo else None)
    library = LightLibrary(data_dir)
    if demo:
        from .demo import DemoScanner, seed

        seed(library)
        scanner = scanner or DemoScanner()
    hub = Hub(store, library, demo=demo, scanner=scanner, pairer=pairer, fps=fps)
    advert_scanner = advert_scanner or (DemoAdvertScanner() if demo else AdvertScanner())

    @asynccontextmanager
    async def lifespan(_app: FastAPI):  # type: ignore[no-untyped-def]
        await hub.start()
        try:
            yield
        finally:
            await hub.stop()
            if on_shutdown is not None:
                on_shutdown()

    app = FastAPI(title="Gaffer light service", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.hub = hub

    def authorised(supplied: str | None) -> bool:
        return token is None or (supplied is not None and secrets.compare_digest(supplied, token))

    @app.middleware("http")
    async def only_known_hosts(request: Request, call_next):  # type: ignore[no-untyped-def]
        # DNS rebinding: a foreign page reaching 127.0.0.1 still names its own host.
        if not host_allowed(request.headers.get("host"), allowed):
            return PlainTextResponse("unknown host", status_code=421)
        # Cross-site request forgery: SameSite does not tell one localhost port from another, so a
        # page on another port could send our cookie with a POST. Browsers always send Origin on those;
        # the Mac shell's URLSession sends none, so a missing Origin is let through (as /ws does).
        if request.method not in ("GET", "HEAD", "OPTIONS") and not origin_allowed(
                request.headers.get("origin"), request.headers.get("host"), allowed):
            return _error(403, "origin_not_allowed", "That page may not change Gaffer's lights.")
        return await call_next(request)

    @app.get("/api/health")
    async def health(request: Request, t: str | None = None) -> Any:
        local = request.client is not None and request.client.host in LOOPBACK
        if not local and not authorised(t):
            return JSONResponse({"error": "token required"}, status_code=401)
        return {"ok": True, "demo": demo, "link": hub.link.snapshot(), "lights": len(hub.fixtures),
                "pid": os.getpid(), "app": "gaffer", "service": "gaffer", "data": str(Path(data_dir).resolve())}

    @app.get("/api/models")
    async def models() -> dict[str, Any]:
        """Every model Gaffer knows, whatever the brand, with the ``features`` the UI lays out controls from."""
        return {"models": models_catalog(), "skipped": skipped_model_files(),
                "drivers": [{"id": d.id} for d in hub.registry.drivers.values()],
                "drivers_skipped": hub.registry.skipped}

    @app.get("/api/lights")
    async def lights() -> dict[str, Any]:
        """Every saved light with its abilities and current state: what the page's hello carries."""
        return hub.lights_view()

    @app.get("/api/looks")
    async def list_looks() -> dict[str, Any]:
        """Every look in slot order (slot 1 first). The Mac shortcuts pick the Nth entry."""
        return {"looks": [looks.view(x) for x in looks.all_looks(hub)]}

    @app.post("/api/looks")
    async def save_look(request: Request) -> Any:
        """Add a look, or replace the one with the same id. No ``lights`` on a new look saves what the lights do now."""
        if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
            return _error(415, "json_required", "Send the look as JSON (Content-Type: application/json).")
        try:
            body = await request.json()
        except ValueError:
            return _error(400, "body_not_json", "Send the look as JSON.")
        try:
            return {"ok": True, "look": looks.view(looks.save(hub, body))}
        except CommandError as err:
            return _error(400, "look_not_valid", str(err))

    @app.post("/api/looks/{look_id}/apply")
    async def apply_look(look_id: str) -> Any:
        try:
            done = looks.apply(hub, look_id)
        except looks.LookNotFound as err:
            return _error(404, "look_not_found", str(err))
        except CommandError as err:
            return _error(409, "look_has_no_lights", str(err))
        return {"ok": True, "look": {"id": done["id"], "name": done["name"]}, "skipped": done["skipped"]}

    @app.post("/api/all-off")
    async def all_off() -> dict[str, Any]:
        """Every light off at once (the Mac shortcut Ctrl-Option-0)."""
        await looks.all_off(hub)
        return {"ok": True}

    @app.get("/api/bluetooth")
    async def bluetooth() -> dict[str, Any]:
        return {"permission": bluetooth_permission()}

    @app.get("/api/scan")
    async def scan(seconds: float = Query(DEFAULT_SCAN_SECONDS)) -> Any:
        """Listen for nearby lights and tag each one's brand family. Listens only; never connects."""
        seconds = max(MIN_SCAN_SECONDS, min(MAX_SCAN_SECONDS, seconds))
        from bleak.exc import BleakBluetoothNotAvailableError

        try:
            result = await advert_scanner.scan(seconds)
        except BleakBluetoothNotAvailableError as err:
            reason = getattr(getattr(err, "reason", None), "name", "")
            logger.warning("bluetooth unavailable: %s (%r)", reason, err)
            return _error(*_BLUETOOTH_ERRORS.get(reason, _BLUETOOTH_UNAVAILABLE))
        except Exception:
            logger.exception("scan failed")
            return _error(500, "scan_failed", "The scan failed. Try again.")
        result["permission"] = bluetooth_permission()
        return result

    scan_page = files("gaffer").joinpath("static/index.html").read_text(encoding="utf-8")

    @app.get("/scan", response_class=HTMLResponse)
    async def scan_proof_page() -> str:
        """SPEC-001's Bluetooth proof page: lists what a scan hears."""
        return scan_page

    @app.get("/api/export")
    async def export(t: str | None = None) -> JSONResponse:
        if not authorised(t):
            return JSONResponse({"error": "token required"}, status_code=401)
        return JSONResponse({**store.snapshot(), "lights": library.public()})

    async def stream_socket(ws: WebSocket) -> None:
        """The stream worker's socket: frames in, nothing out.

        It never reads, so it gets no hello and no 30 Hz state broadcasts, and
        it may only send stream frames. Bad frames are dropped silently: at
        40 frames a second an error reply per frame would just be noise.
        """
        silent = Client()
        try:
            while True:
                try:
                    message = json.loads(await ws.receive_text())
                    if isinstance(message, dict) and message.get("type") in ("stream", "stream.begin", "stream.end"):
                        await dispatch(hub, silent, message)
                except (CommandError, json.JSONDecodeError, ValueError, TypeError):
                    continue
        except WebSocketDisconnect:
            return

    @app.websocket("/ws")
    async def websocket(ws: WebSocket) -> None:
        # Another web page must not drive the lights: only the studio's own page may connect.
        if not origin_allowed(ws.headers.get("origin"), ws.headers.get("host"), allowed):
            await ws.close(code=4403)
            return
        if not authorised(ws.query_params.get("t")):
            await ws.close(code=4401)
            return
        await ws.accept()
        if ws.query_params.get("role") == "stream":
            await stream_socket(ws)
            return
        client = Client()
        client.selected = hub.default_light_id()
        # Hello goes out before the client can receive broadcasts: a state
        # update queued ahead of it would otherwise be overwritten by the older
        # snapshot inside the hello.
        await ws.send_text(json.dumps(hub.hello(client), separators=(",", ":")))
        # The Mac menu bar ignores hello and reads this frame instead: the current look, as the socket opens.
        client.push(looks.frame(hub))
        hub.clients.add(client)

        async def writer() -> None:
            while True:
                await ws.send_text(json.dumps(await client.next(), separators=(",", ":")))

        writer_task = asyncio.create_task(writer())
        running: set[asyncio.Task[Any]] = set()

        async def handle(message: Any) -> None:
            try:
                if not isinstance(message, dict):
                    raise CommandError("messages are JSON objects")
                reply = await dispatch(hub, client, message)
            except (CommandError, TimeoutError) as err:
                reply = {"type": "error", "of": message.get("type") if isinstance(message, dict) else None,
                         "text": str(err) or type(err).__name__}
            except Exception as err:
                # The page gets the error's kind, never its message: that can carry a path on this Mac.
                logger.exception("command failed")
                reply = {"type": "error", "text": f"Something went wrong ({type(err).__name__}). Try again."}
            if reply is not None:
                if isinstance(message, dict) and "rid" in message:
                    reply["rid"] = message["rid"]
                client.push(reply)

        try:
            while True:
                raw = await ws.receive_text()
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError as err:
                    client.push({"type": "error", "of": None, "text": f"not JSON: {err}"})
                    continue
                if isinstance(message, dict) and message.get("type") in LONG_RUNNING:
                    task = asyncio.create_task(handle(message))
                    running.add(task)
                    task.add_done_callback(running.discard)
                else:
                    await handle(message)
        except WebSocketDisconnect:
            pass
        finally:
            hub.clients.discard(client)
            writer_task.cancel()

    if WEB_DIST.exists():
        app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

        @app.get("/{path:path}")
        async def spa(path: str) -> FileResponse:
            candidate = (WEB_DIST / path).resolve()
            if path and candidate.is_file() and WEB_DIST.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(WEB_DIST / "index.html")

    return app
