"""Prove an installation works: ``python -m gaffer --self-test``.

The installers run this last. It needs no Bluetooth and touches none of the
user's data: it starts a demo studio on a free port with a throwaway data
folder, asks it for its health and its page, opens a WebSocket the way the
browser does, and shuts it down again.
"""

from __future__ import annotations

import json
import socket
import sys
import tempfile
import threading
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path

Report = Callable[[str], None]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _get(url: str, timeout: float = 3.0) -> tuple[int, bytes]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.status, response.read()


def run_self_test(report: Report = print, *, require_web: bool = True) -> bool:
    """Run every check, reporting each as it goes. True when all passed."""
    results: list[bool] = []

    def check(name: str, ok: bool, detail: str = "") -> bool:
        results.append(ok)
        report(f"  {'ok  ' if ok else 'FAIL'}  {name}{f': {detail}' if detail else ''}")
        return ok

    check("Python", sys.version_info >= (3, 14), sys.version.split()[0])
    try:
        import bleak
        import cryptography  # noqa: F401
        import godox_mesh_bt  # noqa: F401

        check("Bluetooth library", True, f"bleak {getattr(bleak, '__version__', 'installed')}")
    except Exception as err:  # noqa: BLE001 - report whatever is broken
        check("Bluetooth library", False, str(err))
        return False

    from .catalog import models_index

    check("model table", len(models_index()) >= 180, f"{len(models_index())} Godox models")

    from . import app as app_module

    dist = app_module.WEB_DIST / "index.html"
    if require_web:
        check("web app built", dist.exists(), str(dist) if dist.exists() else f"missing {dist}; run the installer")

    import uvicorn

    from . import demo
    from .app import create_app

    pace, demo.PACE = demo.PACE, 0.05
    with tempfile.TemporaryDirectory(prefix="gaffer-selftest-") as tmp:
        port = _free_port()
        server = uvicorn.Server(uvicorn.Config(create_app(demo=True, data_dir=Path(tmp)), host="127.0.0.1",
                                               port=port, log_level="error"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{port}"
        try:
            health = None
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline and health is None:
                try:
                    _status, body = _get(f"{base}/api/health")
                    health = json.loads(body)
                except OSError:
                    time.sleep(0.2)
            if not check("server", health is not None and health.get("ok") is True,
                         f"answered on port {port}" if health else "did not start"):
                return False
            if require_web and dist.exists():
                status, page = _get(base + "/")
                check("page served", status == 200 and b"<div id=\"root\"" in page)
            from websockets.sync.client import connect

            with connect(f"ws://127.0.0.1:{port}/ws", open_timeout=5) as ws:
                hello = json.loads(ws.recv(timeout=5))
            check("WebSocket", hello.get("type") == "hello" and len(hello.get("lights", [])) == 4,
                  f"{len(hello.get('lights', []))} demo lights")
        except Exception as err:  # noqa: BLE001
            check("server", False, f"{type(err).__name__}: {err}")
        finally:
            server.should_exit = True
            thread.join(10)
            demo.PACE = pace
    return all(results)


def main() -> int:
    print("Gaffer self-test")
    ok = run_self_test()
    print("All good." if ok else "Something is not right; see FAIL above.")
    return 0 if ok else 1
