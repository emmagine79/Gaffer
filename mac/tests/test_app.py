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


def get(port, path, secret=None, host=None):
    """GET a service route as a local tool would: with the session cookie when given."""
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
    if secret:
        req.add_header("Cookie", f"gaffer_session={secret}")
    if host:
        req.add_header("Host", host)
    try:
        with urllib.request.urlopen(req, timeout=WAIT_SECONDS + 5) as r:
            body = r.read()
            return r.status, json.loads(body) if r.headers.get_content_type() == "application/json" else body.decode()
    except urllib.error.HTTPError as err:
        body = err.read()
        try:
            return err.code, json.loads(body)
        except ValueError:
            return err.code, body.decode()


class Launched:
    def __init__(self, app: Path, gaffer: int, child: int, port: int, secret: str):
        self.app, self.gaffer, self.child, self.port, self.secret = app, gaffer, child, port, secret

    def get(self, path, **kw):
        return get(self.port, path, secret=self.secret, **kw)


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

    # The service records its port and secret for local tools in a file only this user can read.
    runtime = Path.home() / f"Library/Application Support/Gaffer/run/service-{child}.json"

    def recorded():
        try:
            return json.loads(runtime.read_text())
        except (FileNotFoundError, ValueError):
            return None

    info = wait_for(recorded, "the service to record its port")
    return Launched(real / "Gaffer.app", gaffer, child, info["port"], info["secret"])


def stop(launched: Launched):
    """End Gaffer; its service then ends by itself. Kill the service only if it doesn't."""
    if alive(launched.gaffer):
        os.kill(launched.gaffer, signal.SIGKILL)
    try:
        wait_for(lambda: not alive(launched.child), "the light service to exit")
    finally:
        if alive(launched.child):
            os.kill(launched.child, signal.SIGKILL)


@pytest.fixture(scope="module")
def gaffer(tmp_path_factory):
    launched = launch(tmp_path_factory.mktemp("gaffer"))
    yield launched
    stop(launched)


def test_double_click_starts_bundled_python_service(gaffer):
    """Criterion 1: signed, with icon, starts its own Python; no Terminal, no system Python."""
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
    status, health = gaffer.get("/api/health")
    assert status == 200 and health["ok"] is True and health["service"] == "gaffer" and health["demo"] is False


def test_bluetooth_permission_is_asked_as_gaffer(gaffer):
    """Criterion 2: macOS checks the Python service's Bluetooth use against Gaffer, not Python.

    tccd logs the subject it decides for each request; the permission prompt names that subject.
    """
    info = plistlib.loads((gaffer.app / "Contents/Info.plist").read_bytes())
    assert "Gaffer" in info["NSBluetoothAlwaysUsageDescription"]
    start = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    time.sleep(1)  # log show --start has one-second resolution
    status, body = gaffer.get("/api/bluetooth")  # a preflight check: never shows a prompt
    assert status == 200

    def subjects():
        out = run("log", "show", "--style", "compact", "--start", start, "--predicate",
                  f'subsystem == "com.apple.TCC" AND eventMessage CONTAINS "AUTHREQ_SUBJECT: msgID={gaffer.child}."')
        return re.findall(r"subject=([^,]+),", out)

    found = wait_for(subjects, "tccd to log the service's Bluetooth check")
    assert set(found) == {BUNDLE_ID}, found


def test_scan_lists_and_tags_nearby_devices(gaffer):
    """Criterion 3: the scan lists nearby BLE devices with a brand family, through the HTTP API."""
    status, body = gaffer.get("/api/bluetooth")
    assert body["permission"] == "allowed", "Bluetooth permission for Gaffer is not granted yet"
    status, body = gaffer.get("/api/scan?seconds=6")
    assert status == 200, body
    assert body["devices"], "no Bluetooth devices heard"
    for device in body["devices"]:
        assert {"id", "name", "rssi", "family", "family_label"} <= device.keys()
    # The window's page and the scan proof page are served by the same service.
    status, page = gaffer.get("/")
    assert status == 200 and "<title>Gaffer</title>" in page
    status, page = gaffer.get("/scan")
    assert status == 200 and "/api/scan" in page


def test_service_has_no_way_to_write_to_a_light(gaffer):
    """Criterion 5: every HTTP route is a read (GET) and errors carry no server paths.

    Since SPEC-002 the lights are driven over the /ws socket, which needs the session cookie
    and the page's own Origin; the scan route listens only. Sending to a light stays behind
    Captain's go-ahead (AGENTS.md).
    """
    status, spec = gaffer.get("/openapi.json")
    methods = {m for ops in spec["paths"].values() for m in ops}
    assert methods == {"get"}, methods
    status, body = gaffer.get("/api/scan?seconds=not-a-number")
    assert status == 422
    assert not re.search(r"/Users/|/private/|/var/", json.dumps(body))


def test_only_gaffers_own_window_can_use_the_service(gaffer):
    """Security (conductor, 18 Oct 2026): a web page can't reach the service by DNS rebinding,
    and nothing without this launch's session secret can use it."""
    status, _ = gaffer.get("/api/health", host="evil.example")
    assert status == 400  # refused by the Host check, even with the right cookie
    for path in ("/api/scan?seconds=2", "/api/health", "/"):
        status, body = get(gaffer.port, path)
        assert status == 401 and body["error"] == "not_signed_in", (path, status, body)
    status, body = get(gaffer.port, "/api/health", secret="not-this-launch")
    assert status == 401
    # Gaffer's window has already used this launch's one-time sign-in link.
    status, body = get(gaffer.port, f"/session?key={gaffer.secret}")
    assert status == 401 and body["error"] == "link_not_valid"


def cpu_seconds(pid):
    """CPU time a process has used so far, from ps ([[dd-]hh:]mm:ss.cc)."""
    total = 0.0
    for part in run("ps", "-o", "time=", "-p", str(pid)).strip().replace("-", ":").split(":"):
        total = total * 60 + float(part)
    return total


def test_gaffer_stays_idle_after_its_service_stops(tmp_path):
    """Regression (verifier, 18 Oct 2026): once the service had gone, Gaffer's stdout
    handler fired again and again at end of file and kept about 2.8 cores busy.

    Runs the real Gaffer binary from a copy of the bundle whose Python is a stand-in
    that announces a port and exits. The stand-in never touches Bluetooth, so macOS
    shows no permission prompt.
    """
    app = tmp_path / "Gaffer.app"
    subprocess.run(["ditto", str(BUILT_APP), str(app)], check=True)
    resources = app / "Contents/Resources"
    (resources / "python/bin/python3.14").write_text(
        "#!/bin/sh\nread secret\necho GAFFER_SERVICE_READY port=9\n: > stand-in-ran\n")
    subprocess.run(["open", "-n", "-g", str(app)], check=True)
    pattern = re.escape(f"{tmp_path.name}/Gaffer.app/Contents/MacOS/Gaffer")
    gaffer = wait_for(lambda: (lambda found: found[0] if len(found) == 1 else None)(pids_matching(pattern)),
                      "Gaffer to start")
    try:
        wait_for(lambda: (resources / "stand-in-ran").exists() and not run("pgrep", "-P", str(gaffer)).strip(),
                 "the stand-in service to exit")
        before, start = cpu_seconds(gaffer), time.monotonic()
        # The fault spun from the moment the service went, so any window shows it; 2 s
        # gives ps (10 ms resolution) a clear reading.
        time.sleep(2)
        used, elapsed = cpu_seconds(gaffer) - before, time.monotonic() - start
        assert alive(gaffer), "Gaffer should stay open and say its service stopped"
        # A spinning thread uses a whole core, so less than one core on average means none spins.
        assert used < elapsed, f"Gaffer used {used:.2f} s of CPU in {elapsed:.2f} s after its service stopped"
    finally:
        if alive(gaffer):
            os.kill(gaffer, signal.SIGKILL)


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
        # It took its port-and-secret record with it.
        assert not (Path.home() / f"Library/Application Support/Gaffer/run/service-{launched.child}.json").exists()
        # Running never changed the signed bundle (python -B writes no .pyc files).
        subprocess.run(["codesign", "--verify", "--deep", "--strict", str(launched.app)], check=True)
    finally:
        stop(launched)
