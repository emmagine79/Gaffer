"""Acceptance test for the built bundle's service (SPEC-002), without launching Gaffer.app.

Build first: scripts/build_app.sh --no-install
Run:        uv run --project service --frozen pytest mac/tests/test_bundle.py

Every rebuild of Gaffer.app has a new ad-hoc signature, so launching it makes macOS ask
for Bluetooth again. This test runs the service the way the app does (the bundle's own
Python, `-I -B -m gaffer --session-from-stdin`) but in --demo mode, which starts no
Bluetooth scan and never touches a light. The bundle is copied into a folder whose path
has a space and reached through a symlink.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BUILT_APP = ROOT / "dist" / "Gaffer.app"
WAIT_SECONDS = 20.0  # launch to ready measured at about 1 s on Captain's Mac Studio, 18 Oct 2026

pytestmark = pytest.mark.skipif(not BUILT_APP.exists(), reason="build dist/Gaffer.app first")


def fetch(port: int, path: str, secret: str) -> tuple[int, str]:
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers={"Cookie": f"gaffer_session={secret}"})
    with urllib.request.urlopen(req, timeout=WAIT_SECONDS) as reply:
        return reply.status, reply.read().decode()


def test_bundled_python_serves_health_scan_and_web_page(tmp_path):
    real = tmp_path / "path with space" / "real"
    real.mkdir(parents=True)
    subprocess.run(["ditto", str(BUILT_APP), str(real / "Gaffer.app")], check=True)
    (tmp_path / "link").symlink_to(real)
    python = tmp_path / "link" / "Gaffer.app" / "Contents" / "Resources" / "python" / "bin" / "python3.14"
    home = tmp_path / "home"
    home.mkdir()
    secret = "bundle-test-secret"
    service = subprocess.Popen(
        [str(python), "-I", "-B", "-m", "gaffer", "--demo", "--session-from-stdin", "--data", str(tmp_path / "data")],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        env={"HOME": str(home), "PATH": "/usr/bin:/bin"}, start_new_session=True,
    )
    try:
        service.stdin.write(secret + "\n")
        service.stdin.flush()
        deadline = time.monotonic() + WAIT_SECONDS
        line = ""
        while "GAFFER_SERVICE_READY" not in line:
            assert time.monotonic() < deadline and service.poll() is None, "the bundled service did not start"
            line = service.stdout.readline()
        port = int(line.split("port=")[1])

        status, body = fetch(port, "/api/health", secret)
        health = json.loads(body)
        assert status == 200 and health["ok"] is True and health["service"] == "gaffer" and health["demo"] is True
        assert health["lights"] > 0  # lumen-studio's demo lights, from the renamed package

        status, body = fetch(port, "/api/scan?seconds=2", secret)
        families = {d["name"]: d["family"] for d in json.loads(body)["devices"]}
        assert status == 200 and families["GD_LED"] == "godox_mesh" and families["PL000_DEMO"] == "zhiyun"

        status, page = fetch(port, "/", secret)  # the web page built from web/ rides inside the bundle
        assert status == 200 and "<title>Gaffer</title>" in page and "/assets/" in page

        # The service ends when its stdin closes, as it does when Gaffer quits.
        service.stdin.close()
        assert service.wait(timeout=WAIT_SECONDS) == 0
    finally:
        if service.poll() is None:
            os.killpg(service.pid, signal.SIGKILL)
            service.wait()
