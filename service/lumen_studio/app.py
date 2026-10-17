"""HTTP and WebSocket surface."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .commands import CommandError, dispatch
from .guard import LOCAL_HOSTS, LOOPBACK, host_allowed, origin_allowed
from .hub import Client, Hub
from .lights import LightLibrary
from .store import Store

logger = logging.getLogger(__name__)

#: Commands that can take seconds (a scan, a pairing, a move to another network).
#: They run beside the socket's loop, so sliders keep working meanwhile, and
#: answer by request id when they finish.
LONG_RUNNING = frozenset({"lights.scan", "lights.pair", "lights.import", "select"})

STUDIO_ROOT = Path(__file__).resolve().parents[2]
WEB_DIST = STUDIO_ROOT / "web" / "dist"


def create_app(
    *,
    demo: bool,
    data_dir: Path,
    token: str | None = None,
    scanner: Any = None,
    pairer: Any = None,
    fps: float = 60.0,
    hosts: tuple[str, ...] = (),
) -> FastAPI:
    """The studio app. ``hosts`` adds names it may be reached by (the LAN address with --lan)."""
    allowed = LOCAL_HOSTS | frozenset(h.lower() for h in hosts)
    store = Store(data_dir)
    library = LightLibrary(data_dir)
    if demo:
        from .demo import DemoScanner, seed

        seed(library)
        scanner = scanner or DemoScanner()
    hub = Hub(store, library, demo=demo, scanner=scanner, pairer=pairer, fps=fps)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):  # type: ignore[no-untyped-def]
        await hub.start()
        try:
            yield
        finally:
            await hub.stop()

    app = FastAPI(title="Lumen Studio", lifespan=lifespan)
    app.state.hub = hub

    def authorised(supplied: str | None) -> bool:
        return token is None or (supplied is not None and secrets.compare_digest(supplied, token))

    @app.middleware("http")
    async def only_known_hosts(request: Request, call_next):  # type: ignore[no-untyped-def]
        # DNS rebinding: a foreign page reaching 127.0.0.1 still names its own host.
        if not host_allowed(request.headers.get("host"), allowed):
            return PlainTextResponse("unknown host", status_code=421)
        return await call_next(request)

    @app.get("/api/health")
    async def health(request: Request, t: str | None = None) -> Any:
        local = request.client is not None and request.client.host in LOOPBACK
        if not local and not authorised(t):
            return JSONResponse({"error": "token required"}, status_code=401)
        return {"ok": True, "demo": demo, "link": hub.link.snapshot(), "lights": len(hub.fixtures),
                "pid": os.getpid(), "app": "lumen-studio", "data": str(Path(data_dir).resolve())}

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
                logger.exception("command failed")
                reply = {"type": "error", "text": f"{type(err).__name__}: {err}"}
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
