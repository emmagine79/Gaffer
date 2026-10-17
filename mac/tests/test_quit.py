"""Acceptance tests for SPEC-017: quitting Gaffer leaves no Python process, and service.log stays small.

Build first: scripts/build_app.sh --no-install
Run:        uv run --project service --frozen pytest mac/tests/test_quit.py

These do not open Gaffer.app, a window or Bluetooth. They compile the real mac/Sources/ServiceProcess.swift
and ServiceLog.swift with a small driver (service_process_check.swift) and run it against the bundle's own
Python in --demo mode, from a folder with a space in its path reached through a symlink. The driver starts
the service exactly as the app does, then ends the way the app ends: Quit calls ServiceProcess.stop(),
a crash is SIGKILL (the kernel closes the stdin pipe the service is watching).
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from pathlib import Path

import pytest
from gaffer.__main__ import BACKSTOP_SECONDS

ROOT = Path(__file__).resolve().parents[2]
BUILT_APP = ROOT / "dist" / "Gaffer.app"
SOURCES = ROOT / "mac" / "Sources"
CHECK = Path(__file__).with_name("service_process_check.swift")
# The service's own limit for a stop is BACKSTOP_SECONDS (service/gaffer/__main__.py, measured there);
# a little more covers the process starting up and the test noticing.
EXIT_WITHIN_SECONDS = BACKSTOP_SECONDS + 10.0
START_WITHIN_SECONDS = 60.0  # the driver's own limit for the service to announce its port

pytestmark = pytest.mark.skipif(not BUILT_APP.exists(), reason="build dist/Gaffer.app first")


@pytest.fixture(scope="module")
def rig(tmp_path_factory):
    base = tmp_path_factory.mktemp("quit")
    real = base / "path with space" / "real"
    real.mkdir(parents=True)
    subprocess.run(["ditto", str(BUILT_APP), str(real / "Gaffer.app")], check=True)
    (base / "link").symlink_to(real)
    build = base / "driver"
    build.mkdir()
    (build / "main.swift").write_text(CHECK.read_text())
    subprocess.run(
        ["swiftc", "-swift-version", "5", "-target", "arm64-apple-macos14.0",
         str(SOURCES / "ServiceProcess.swift"), str(SOURCES / "ServiceLog.swift"), str(build / "main.swift"),
         "-o", str(build / "service_process_check")],
        check=True, capture_output=True, text=True)
    return {"resources": base / "link" / "Gaffer.app" / "Contents" / "Resources",
            "driver": build / "service_process_check", "base": base}


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def pids_matching(text: str) -> list[int]:
    out = subprocess.run(["pgrep", "-f", text], capture_output=True, text=True).stdout
    return [int(p) for p in out.split()]


class Run:
    """One driver process with the service running under it."""

    def __init__(self, rig, name: str, mode: str, logs: Path | None = None):
        self.data = rig["base"] / f"data-{name}"
        self.logs = logs or rig["base"] / f"logs-{name}"
        home = rig["base"] / f"home-{name}"  # the service's run file goes under HOME, not Captain's real one
        home.mkdir()
        self.driver = subprocess.Popen(
            [str(rig["driver"]), str(rig["resources"]), str(self.data), str(self.logs), mode],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
            env={"HOME": str(home), "PATH": "/usr/bin:/bin"}, start_new_session=True)
        deadline = time.monotonic() + START_WITHIN_SECONDS
        line = ""
        while not line.startswith("READY"):
            assert time.monotonic() < deadline and self.driver.poll() is None, f"driver said: {line!r}"
            line = self.driver.stdout.readline()
        out = subprocess.run(["pgrep", "-P", str(self.driver.pid)], capture_output=True, text=True).stdout.split()
        assert len(out) == 1, "the driver should have exactly one child, the Python service"
        self.child = int(out[0])

    def quit(self) -> None:
        self.driver.stdin.write("go\n")
        self.driver.stdin.flush()
        assert self.driver.wait(timeout=EXIT_WITHIN_SECONDS) == 0
        assert "STOPPED" in self.driver.stdout.read()

    def crash(self) -> None:
        os.killpg(self.driver.pid, signal.SIGKILL)
        self.driver.wait()

    def cleanup(self) -> None:
        if self.driver.poll() is None:
            os.killpg(self.driver.pid, signal.SIGKILL)
            self.driver.wait()
        if alive(self.child):
            os.kill(self.child, signal.SIGKILL)


def wait_gone(pid: int) -> None:
    deadline = time.monotonic() + EXIT_WITHIN_SECONDS
    while alive(pid):
        assert time.monotonic() < deadline, f"process {pid} is still running"
        time.sleep(0.1)


@pytest.mark.parametrize("how", ["quit", "crash"])
def test_quitting_leaves_no_python_process_and_the_service_saved_its_state(rig, how):
    """Criterion 2: however Gaffer ends, its Python service ends, and ends cleanly (state saved)."""
    run = Run(rig, how, "quit" if how == "quit" else "wait")
    try:
        assert alive(run.child)
        getattr(run, how)()
        wait_gone(run.child)
        assert pids_matching(str(run.data)) == [], "a Python process for this data folder is still running"
        # Hub.stop saves the lights' state; the hard-exit backstop does not. So this file exists only if
        # the service stopped cleanly rather than being cut off (SPEC-002 review issue).
        saved = json.loads((run.data / "settings.json").read_text())
        assert "light_states" in saved
    finally:
        run.cleanup()


def test_service_log_keeps_only_this_run_and_the_one_before(rig):
    """Criterion: service.log can't grow without bound. Each launch keeps the current and previous run only."""
    logs = rig["base"] / "logs-rotation"
    seen: list[int] = []
    for n in range(3):
        run = Run(rig, f"rot{n}", "quit", logs=logs)
        try:
            seen.append(run.child)
            run.quit()
            wait_gone(run.child)
        finally:
            run.cleanup()
        assert sorted(p.name for p in logs.iterdir()) == (
            ["service.log"] if n == 0 else ["service.log", "service.previous.log"])
        current = (logs / "service.log").read_text()
        assert f"[{seen[n]}]" in current  # uvicorn's "Started server process [pid]" line
        if n:
            assert f"[{seen[n - 1]}]" not in current
            assert f"[{seen[n - 1]}]" in (logs / "service.previous.log").read_text()
        if n > 1:
            assert f"[{seen[n - 2]}]" not in (logs / "service.previous.log").read_text()
