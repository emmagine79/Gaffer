"""A small stand-in for Gaffer's light service, for the shell's tests.

It speaks contracts/api.md and nothing else: the Host and cookie rules, the
one-time /session link, GET /api/looks, POST apply, all-off and cue go, the page
at /?surface=..., and the /ws `look` messages. It has three demo lights in memory.
It never touches Bluetooth, so macOS shows no permission prompt.

It starts the way the real service does: the first line on stdin is the session
secret, it prints `GAFFER_SERVICE_READY port=N`, and it exits when stdin closes.
Python standard library only, because the app runs it with the test's own Python.

Test-only routes (same cookie rule), used by mac/tests/test_shell.py:
  GET  /test/state      what happened: calls, lights, current look, page reports
  POST /test/report     the demo page tells what it saw (surface, look name, colour scheme)
  POST /test/drop-ws    close every WebSocket from the service side
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import hmac
import json
import os
import struct
import sys
import time
from urllib.parse import parse_qs, unquote, urlsplit

COOKIE = "gaffer_session"
GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"  # RFC 6455

LOOKS = [
    {"id": "talking-head", "name": "Talking head", "lights": {"key": True, "fill": True, "back": False}},
    {"id": "interview", "name": "Interview", "lights": {"key": True, "fill": True, "back": True}},
    {"id": "sunset", "name": "Sunset", "lights": {"key": False, "fill": False, "back": True}},
]
CUE = ["talking-head", "interview", "sunset"]
HTML = """<!doctype html><meta charset="utf-8"><meta name="color-scheme" content="light dark">
<title>Gaffer stand-in</title>
<style>:root{color-scheme:light dark}body{font:16px -apple-system,sans-serif;padding:16px}</style>
<h1 id="look">No look</h1><p id="surface"></p>
<script>
const surface = new URLSearchParams(location.search).get('surface');
document.getElementById('surface').textContent = 'surface: ' + surface;
const scheme = () => matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
let name = null;
const report = () => fetch('/test/report', {method: 'POST', body: JSON.stringify({surface, name, scheme: scheme()})});
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', report);
const ws = new WebSocket('ws://' + location.host + '/ws');
ws.onmessage = (e) => {
  const m = JSON.parse(e.data);
  if (m.type === 'look') { name = m.name; document.getElementById('look').textContent = name || 'No look'; report(); }
};
report();
</script>
"""


class Service:
    def __init__(self, secret: str) -> None:
        self.secret = secret
        self.link_used = False
        self.lights = {"key": False, "fill": False, "back": False}
        self.look: str | None = None
        self.cue_pos = -1
        self.calls: list[dict] = []
        self.reports: dict[str, dict] = {}  # latest report per surface
        self.clients: list[asyncio.StreamWriter] = []
        self.ws_opened = 0

    # -- the contract -------------------------------------------------------

    def set_look(self, look: dict | None) -> None:
        self.look = look["name"] if look else None
        if look:
            self.lights.update(look["lights"])
        else:
            self.lights = {k: False for k in self.lights}
        for writer in list(self.clients):
            self.send_look(writer)

    def send_look(self, writer: asyncio.StreamWriter) -> None:
        payload = json.dumps({"type": "look", "name": self.look}).encode()
        header = b"\x81" + (bytes([len(payload)]) if len(payload) < 126 else b"\x7e" + struct.pack(">H", len(payload)))
        try:
            writer.write(header + payload)
        except Exception:
            pass

    def api(self, method: str, path: str) -> tuple[int, dict]:
        if method == "GET" and path == "/api/health":
            return 200, {"ok": True, "service": "gaffer"}
        if method == "GET" and path == "/api/looks":
            return 200, {"looks": [{"id": x["id"], "name": x["name"]} for x in LOOKS]}
        if method == "POST" and path.startswith("/api/looks/") and path.endswith("/apply"):
            look_id = unquote(path[len("/api/looks/"):-len("/apply")])
            look = next((x for x in LOOKS if x["id"] == look_id), None)
            if look is None:
                return 404, {"error": "look_not_found", "message": "There is no look with that id."}
            self.set_look(look)
            return 200, {"ok": True, "look": {"id": look["id"], "name": look["name"]}}
        if method == "POST" and path == "/api/all-off":
            self.set_look(None)
            return 200, {"ok": True}
        if method == "POST" and path == "/api/cues/active/go":
            self.cue_pos = (self.cue_pos + 1) % len(CUE)
            look = next(x for x in LOOKS if x["id"] == CUE[self.cue_pos])
            self.set_look(look)
            return 200, {"ok": True, "look": {"id": look["id"], "name": look["name"]}}
        return 404, {"error": "not_found", "message": "No such route."}


def refuse(status: int, code: str, message: str) -> tuple[int, dict]:
    return status, {"error": code, "message": message}


async def read_request(reader: asyncio.StreamReader):
    try:
        head = await reader.readuntil(b"\r\n\r\n")
    except (asyncio.IncompleteReadError, ConnectionError):
        return None
    lines = head.decode("latin-1").split("\r\n")
    method, target, _ = lines[0].split(" ", 2)
    headers = {}
    for line in lines[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    body = b""
    if int(headers.get("content-length", 0)):
        body = await reader.readexactly(int(headers["content-length"]))
    return method, target, headers, body


def respond(writer, status: int, body: bytes, content_type: str, extra: list[str] | None = None) -> None:
    reason = {200: "OK", 303: "See Other", 400: "Bad Request", 401: "Unauthorized", 404: "Not Found"}.get(status, "OK")
    lines = [f"HTTP/1.1 {status} {reason}", f"Content-Type: {content_type}", f"Content-Length: {len(body)}"]
    lines += extra or []
    writer.write(("\r\n".join(lines) + "\r\n\r\n").encode() + body)


def cookie_value(headers: dict) -> str | None:
    for part in headers.get("cookie", "").split(";"):
        k, _, v = part.strip().partition("=")
        if k == COOKIE:
            return v
    return None


async def ws_loop(service: Service, reader, writer) -> None:
    """Read frames until the client closes. Answer pings and close."""
    try:
        while True:
            first, second = await reader.readexactly(2)
            opcode, length = first & 0x0F, second & 0x7F
            if length == 126:
                length = struct.unpack(">H", await reader.readexactly(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", await reader.readexactly(8))[0]
            mask = await reader.readexactly(4) if second & 0x80 else b""
            data = await reader.readexactly(length)
            if mask:
                data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
            if opcode == 0x8:
                writer.write(b"\x88\x00")
                break
            if opcode == 0x9:
                writer.write(b"\x8a" + bytes([len(data)]) + data)
    except (asyncio.IncompleteReadError, ConnectionError):
        pass
    finally:
        if writer in service.clients:
            service.clients.remove(writer)


async def handle(service: Service, reader, writer) -> None:
    try:
        while True:
            request = await read_request(reader)
            if request is None:
                break
            method, target, headers, body = request
            split = urlsplit(target)
            path, query = split.path, parse_qs(split.query)
            host = headers.get("host", "").rsplit(":", 1)[0]
            record = {"method": method, "path": path, "query": split.query, "t": time.monotonic()}
            if path.startswith(("/api/", "/session")):
                service.calls.append(record)

            if host not in ("127.0.0.1", "localhost"):
                status, payload = refuse(400, "bad_host", "Invalid host header.")
            elif path == "/session":
                if service.link_used or not hmac.compare_digest((query.get("key") or [""])[0], service.secret):
                    status, payload = refuse(401, "link_not_valid", "This sign-in link is not valid.")
                else:
                    service.link_used = True
                    respond(writer, 303, b"", "text/plain", ["Location: /",
                            f"Set-Cookie: {COOKIE}={service.secret}; Path=/; HttpOnly; SameSite=Strict"])
                    continue
            elif not hmac.compare_digest(cookie_value(headers) or "", service.secret):
                status, payload = refuse(401, "not_signed_in", "Open Gaffer from the menu bar to use it.")
            elif path == "/ws" and headers.get("upgrade", "").lower() == "websocket":
                accept = base64.b64encode(hashlib.sha1((headers["sec-websocket-key"] + GUID).encode()).digest()).decode()
                writer.write(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                              f"Sec-WebSocket-Accept: {accept}\r\n\r\n").encode())
                service.clients.append(writer)
                service.ws_opened += 1
                service.send_look(writer)  # contract: current look as soon as the socket opens
                await ws_loop(service, reader, writer)
                return
            elif path == "/":
                respond(writer, 200, HTML.encode(), "text/html; charset=utf-8")
                service.calls.append({**record, "page": True})
                continue
            elif path == "/test/state":
                status, payload = 200, {
                    "calls": service.calls, "lights": service.lights, "look": service.look,
                    "reports": service.reports, "clients": len(service.clients), "ws_opened": service.ws_opened,
                    "now": time.monotonic(),
                }
            elif path == "/test/report" and method == "POST":
                report = json.loads(body or b"{}")
                service.reports[str(report.get("surface"))] = {**report, "t": time.monotonic()}
                status, payload = 200, {"ok": True}
            elif path == "/test/drop-ws":
                for client in list(service.clients):
                    client.close()
                service.clients.clear()
                status, payload = 200, {"ok": True}
            else:
                status, payload = service.api(method, path)
            respond(writer, status, json.dumps(payload).encode(), "application/json")
            if headers.get("connection", "").lower() == "close":
                break
    except Exception as err:  # a bad request must not end the stand-in
        print(f"stand-in: {type(err).__name__}", file=sys.stderr, flush=True)
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-file", required=True)
    args, _ = parser.parse_known_args()

    loop = asyncio.get_running_loop()
    stdin = asyncio.StreamReader()
    await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(stdin), sys.stdin)
    secret = (await stdin.readline()).decode().strip()
    if not secret:
        return

    service = Service(secret)
    server = await asyncio.start_server(lambda r, w: handle(service, r, w), "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    with open(args.state_file, "w") as f:
        json.dump({"pid": os.getpid(), "port": port, "secret": secret}, f)
    print(f"GAFFER_SERVICE_READY port={port}", flush=True)

    await stdin.read()  # returns at end of file: Gaffer has gone, so does the service
    os._exit(0)


if __name__ == "__main__":
    asyncio.run(main())
