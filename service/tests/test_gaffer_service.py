"""Acceptance tests for the merged Gaffer service (SPEC-002), through the real app.

They drive the app Gaffer.app runs: lumen-studio's engine, SPEC-001's scan and
session guard. Demo mode, so no Bluetooth is touched.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from websockets.sync.client import connect

from gaffer import app as app_module
from gaffer.app import create_app
from gaffer.hub import SAVE_AFTER_SECONDS
from gaffer.paths import data_home
from gaffer.session import COOKIE, protect

SECRET = "test-secret-for-this-launch"
WS = "ws://127.0.0.1/ws"  # TestClient ignores base_url for sockets


@pytest.fixture
def window(tmp_path):
    """The app as the Mac window reaches it: behind the Host check and the session secret."""
    app = create_app(demo=True, data_dir=tmp_path)
    with TestClient(protect(app, SECRET), base_url="http://127.0.0.1") as client:
        yield client


def sign_in(client: TestClient) -> None:
    reply = client.get(f"/session?key={SECRET}", follow_redirects=False)
    assert reply.status_code == 303 and client.cookies.get(COOKIE) == SECRET


def test_data_folder_is_gaffer_and_gaffer_home_moves_it(tmp_path):
    """Criterion 1: LUMEN_HOME became GAFFER_HOME and the app folder is Gaffer."""
    assert data_home({"HOME": str(tmp_path)}, "darwin") == tmp_path / "Library" / "Application Support" / "Gaffer"
    assert data_home({"HOME": str(tmp_path), "GAFFER_HOME": str(tmp_path / "x")}, "darwin") == tmp_path / "x"
    assert data_home({"HOME": str(tmp_path), "LUMEN_HOME": str(tmp_path / "x")}, "darwin") != tmp_path / "x"


def test_health_and_scan_are_served_by_the_merged_service(window):
    """Criterion 2: /api/health and SPEC-001's scan work from the renamed package."""
    sign_in(window)
    health = window.get("/api/health").json()
    assert health["ok"] is True and health["service"] == "gaffer" and health["demo"] is True
    scan = window.get("/api/scan?seconds=2").json()
    families = {d["name"]: d["family"] for d in scan["devices"]}
    assert families["GD_LED"] == "godox_mesh" and families["YN-DEMO"] == "yongnuo" and families["PL000_DEMO"] == "zhiyun"
    assert families["Someone's phone"] is None and scan["skipped"] == []


def test_session_guard_covers_pages_api_and_the_light_socket(window):
    """SPEC-001's loopback guard still holds, and now also covers lumen's /ws."""
    assert window.get("/api/health").status_code == 401
    assert window.get("/api/health", headers={"host": "evil.example"}).status_code == 400
    with pytest.raises(WebSocketDisconnect) as refused, window.websocket_connect(WS):
        pass
    assert refused.value.code == 4401
    sign_in(window)
    assert window.get(f"/session?key={SECRET}").status_code == 401  # the link works once
    with window.websocket_connect(WS) as ws:
        assert ws.receive_json()["type"] == "hello"
    # lumen's own Origin check still refuses another site's page, even when signed in.
    with pytest.raises(WebSocketDisconnect), window.websocket_connect(WS, headers={"origin": "http://evil.example"}):
        pass


def test_a_failing_command_never_shows_a_path_on_this_mac(window, monkeypatch):
    """Errors reach the page as plain words: the raw message (here a path) stays in the log."""

    async def broken(*_args, **_kwargs):
        raise OSError("/Users/someone/Library/Application Support/Gaffer/lights.json is unreadable")

    monkeypatch.setattr(app_module, "dispatch", broken)
    sign_in(window)
    with window.websocket_connect(WS) as ws:
        ws.receive_json()
        ws.send_json({"type": "select", "light": "x"})
        reply = next(m for m in (ws.receive_json() for _ in range(50)) if m["type"] == "error")  # broadcasts come between
    assert reply["type"] == "error" and not re.search(r"/Users/|/private/|/var/", reply["text"])


def test_quitting_gaffer_saves_the_last_light_state(tmp_path):
    """Quit closes the service's stdin. The service must stop cleanly, so the last change is saved.

    Runs the service the way Gaffer.app does (python -I -B -m gaffer --session-from-stdin), in --demo.
    """
    data = tmp_path / "data"
    service = subprocess.Popen(
        [sys.executable, "-I", "-B", "-m", "gaffer", "--demo", "--session-from-stdin", "--data", str(data)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}, start_new_session=True,
    )
    try:
        service.stdin.write(SECRET + "\n")
        service.stdin.flush()
        line = ""
        while "GAFFER_SERVICE_READY" not in line:
            assert service.poll() is None, "the service did not start"
            line = service.stdout.readline()
        port = int(line.split("port=")[1])
        with connect(f"ws://127.0.0.1:{port}/ws", additional_headers={"Cookie": f"gaffer_session={SECRET}"}) as ws:
            light = json.loads(ws.recv())["selected"]
            ws.send(json.dumps({"type": "set", "light": light, "patch": {"brightness": 17}}))
            while not (
                (m := json.loads(ws.recv(timeout=10))).get("type") == "state"
                and m["light"] == light and m["state"]["brightness"] == 17
            ):
                pass
            changed = time.monotonic()  # the hub's own save falls due SAVE_AFTER_SECONDS after the change
            service.stdin.close()  # what Quit Gaffer does
            assert service.wait(timeout=30) == 0
            # Gone before that save was due, so the state on disk came from a clean Hub.stop.
            assert time.monotonic() - changed < SAVE_AFTER_SECONDS
        assert json.loads((data / "settings.json").read_text())["light_states"][light]["brightness"] == 17
    finally:
        if service.poll() is None:
            os.killpg(service.pid, signal.SIGKILL)
            service.wait()
