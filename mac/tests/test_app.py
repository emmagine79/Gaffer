"""Acceptance tests for the built Gaffer.app, through the real app.

Build first: scripts/build_app.sh --no-install
Run:        uv run --project service --frozen pytest mac/tests

Each test copies dist/Gaffer.app into a folder whose path has a space, reaches it
through a symlink, and launches it with `open`, the way a double-click does.
Bluetooth permission must already be granted to Gaffer for the scan test.
"""

from __future__ import annotations

import json
import os
import plistlib
import re
import signal
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BUILT_APP = ROOT / "dist" / "Gaffer.app"
BUNDLE_ID = "work.awelahlayray.gaffer"

# Bound for every wait below. The longest single thing the service does is a scan,
# at most 20 s (MAX_SCAN_SECONDS, lumen-studio's clamp). Launch to ready measured
# at about 1 s on Captain's Mac Studio, 18 Oct 2026.
WAIT_SECONDS = 20.0

pytestmark = pytest.mark.skipif(not BUILT_APP.exists(), reason="build dist/Gaffer.app first")


def wait_for(check, what):
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(0.2)
    raise AssertionError(f"timed out waiting for {what}")


def run(*cmd):
    return subprocess.run(cmd, capture_output=True, text=True).stdout


def pids_matching(pattern):
    return [int(p) for p in run("pgrep", "-f", pattern).split()]


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def get(port, path):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=WAIT_SECONDS + 5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read())


class Launched:
    def __init__(self, app: Path, gaffer: int, child: int, port: int):
        self.app, self.gaffer, self.child, self.port = app, gaffer, child, port


def launch(tmp: Path) -> Launched:
    real = tmp / "path with space" / "real"
    real.mkdir(parents=True)
    subprocess.run(["ditto", str(BUILT_APP), str(real / "Gaffer.app")], check=True)
    link = tmp / "link"
    link.symlink_to(real)
    app = link / "Gaffer.app"
    subprocess.run(["open", "-n", "-g", str(app)], check=True)
    pattern = re.escape(f"{tmp.parent.name}/{tmp.name}/") + r".*Gaffer\.app/Contents/MacOS/Gaffer"

    def gaffer_pid():
        found = pids_matching(pattern)
        return found[0] if len(found) == 1 else None

    gaffer = wait_for(gaffer_pid, "Gaffer to start")
    child = wait_for(lambda: next(iter(int(p) for p in run("pgrep", "-P", str(gaffer)).split()), None),
                     "the light service to start")

    def port():
        m = re.search(r"n127\.0\.0\.1:(\d+)", run("lsof", "-a", "-p", str(child), "-iTCP", "-sTCP:LISTEN", "-n", "-P", "-Fn"))
        return int(m.group(1)) if m else None

    return Launched(real / "Gaffer.app", gaffer, child, wait_for(port, "the service to listen"))


def stop(launched: Launched):
    for pid in (launched.gaffer, launched.child):
        if alive(pid):
            os.kill(pid, signal.SIGKILL)


@pytest.fixture(scope="module")
def gaffer(tmp_path_factory):
    launched = launch(tmp_path_factory.mktemp("gaffer"))
    yield launched
    stop(launched)


def test_double_click_starts_bundled_python_service(gaffer):
    """Criterion 1: ad-hoc signed, with icon, starts its own Python; no Terminal, no system Python."""
    contents = gaffer.app / "Contents"
    info = plistlib.loads((contents / "Info.plist").read_bytes())
    assert (contents / "Resources" / f"{info['CFBundleIconFile']}.icns").is_file()
    signature = subprocess.run(["codesign", "-dv", str(gaffer.app)], capture_output=True, text=True).stderr
    assert "Signature=adhoc" in signature and f"Identifier={BUNDLE_ID}" in signature

    # Gaffer was started by launchd (as from Finder), not by a shell or Terminal.
    assert run("ps", "-o", "ppid=", "-p", str(gaffer.gaffer)).strip() == "1"
    assert run("ps", "-o", "ppid=", "-p", str(gaffer.child)).strip() == str(gaffer.gaffer)
    # The service's executable file is the Python inside this copy of the bundle.
    exe = run("lsof", "-a", "-p", str(gaffer.child), "-d", "txt", "-Fn").split("\nn", 1)[1].splitlines()[0]
    assert Path(exe).resolve() == (contents / "Resources/python/bin/python3.14").resolve()
    assert get(gaffer.port, "/api/health") == (200, {"ok": True, "service": "gaffer"})


def test_bluetooth_permission_is_asked_as_gaffer(gaffer):
    """Criterion 2: macOS checks the Python service's Bluetooth use against Gaffer, not Python.

    tccd logs the subject it decides for each request; the permission prompt names that subject.
    """
    info = plistlib.loads((gaffer.app / "Contents/Info.plist").read_bytes())
    assert "Gaffer" in info["NSBluetoothAlwaysUsageDescription"]
    start = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    time.sleep(1)  # log show --start has one-second resolution
    status, body = get(gaffer.port, "/api/bluetooth")  # a preflight check: never shows a prompt
    assert status == 200

    def subjects():
        out = run("log", "show", "--style", "compact", "--start", start, "--predicate",
                  f'subsystem == "com.apple.TCC" AND eventMessage CONTAINS "AUTHREQ_SUBJECT: msgID={gaffer.child}."')
        return re.findall(r"subject=([^,]+),", out)

    found = wait_for(subjects, "tccd to log the service's Bluetooth check")
    assert set(found) == {BUNDLE_ID}, found


def test_scan_lists_and_tags_nearby_devices(gaffer):
    """Criterion 3: the scan lists nearby BLE devices with a brand family, through the HTTP API."""
    status, body = get(gaffer.port, "/api/bluetooth")
    assert body["permission"] == "allowed", "Bluetooth permission for Gaffer is not granted yet"
    status, body = get(gaffer.port, "/api/scan?seconds=6")
    assert status == 200, body
    assert body["devices"], "no Bluetooth devices heard"
    for device in body["devices"]:
        assert {"id", "name", "rssi", "family", "family_label"} <= device.keys()
    # The page the window shows is served by the same service.
    with urllib.request.urlopen(f"http://127.0.0.1:{gaffer.port}/", timeout=WAIT_SECONDS) as r:
        assert "/api/scan" in r.read().decode()


def test_service_has_no_way_to_write_to_a_light(gaffer):
    """Criterion 5: the service's whole API is read-only, and its errors carry no server paths."""
    status, spec = get(gaffer.port, "/openapi.json")
    methods = {m for ops in spec["paths"].values() for m in ops}
    assert methods == {"get"}, methods
    status, body = get(gaffer.port, "/api/scan?seconds=not-a-number")
    assert status == 422
    assert not re.search(r"/Users/|/private/|/var/", json.dumps(body))


@pytest.mark.parametrize("how", ["quit", "SIGINT", "SIGTERM", "SIGKILL"])
def test_quitting_gaffer_leaves_no_service(tmp_path, how):
    """Criterion 4: however Gaffer ends, its Python service ends too."""
    launched = launch(tmp_path)
    try:
        if how == "quit":
            # The Quit menu item and Cmd-Q both send this Apple Event.
            # Sent to this one instance, so another running Gaffer is left alone.
            script = ("ObjC.import('AppKit'); "
                      f"$.NSRunningApplication.runningApplicationWithProcessIdentifier({launched.gaffer}).terminate")
            subprocess.run(["osascript", "-l", "JavaScript", "-e", script], check=True)
        else:
            os.kill(launched.gaffer, getattr(signal, how))
        wait_for(lambda: not alive(launched.gaffer), "Gaffer to exit")
        wait_for(lambda: not alive(launched.child), "the light service to exit")
        # Running never changed the signed bundle (python -B writes no .pyc files).
        subprocess.run(["codesign", "--verify", "--deep", "--strict", str(launched.app)], check=True)
    finally:
        stop(launched)
