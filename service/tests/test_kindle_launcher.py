"""The Kindle launcher (kindle/gaffer_remote.sh), run for real under a POSIX shell.

The Kindle's own tools (eips, lipc-set-prop, stop, start, usleep, killall) are stand-ins on PATH that
write what they were asked to a log. The power button is a named pipe: writing a 16-byte input_event
to it is a press. The browser is a stand-in that stays open until killed, or closes when told.

Its promises: one power press gives the Kindle's screens back and lets it sleep; a browser that
closes by itself does the same with no press; with no power button to read it never stops the
Kindle's screens; the stop scriptlet closes a running remote.
"""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
import time
from pathlib import Path

KINDLE = Path(__file__).resolve().parents[2] / "kindle"
SHELL = shutil.which("dash") or "/bin/sh"  # dash is close to the Kindle's BusyBox sh; no bash-isms

TOOLS = ["eips", "lipc-set-prop", "stop", "start", "killall"]
DEVICES = """I: Bus=0019 Vendor=0001 Product=0001 Version=0100
N: Name="bd71827-power"
H: Handlers=kbd event1

I: Bus=0018 Vendor=0000 Product=0000 Version=0000
N: Name="cyttsp5_mt"
H: Handlers=event2
"""


def _press() -> bytes:
    """A KEY_POWER press as the Kindle's 32-bit kernel writes it: time, then type, code, value."""
    return struct.pack("<IIHHi", 1, 0, 1, 116, 1)


class Kindle:
    def __init__(self, root: Path, *, devices: str = DEVICES, browser_seconds: int | None = None) -> None:
        self.root = root
        self.log = root / "log"
        self.log.touch()
        bin_dir = root / "bin"
        bin_dir.mkdir()
        for tool in TOOLS:
            (bin_dir / tool).write_text(f'#!/bin/sh\necho "{tool} $*" >> "{self.log}"\n')
        (bin_dir / "usleep").write_text("#!/bin/sh\nexit 0\n")
        life = "exec sleep 600" if browser_seconds is None else f"sleep {browser_seconds}"
        browser = root / "kindle_browser"
        browser.write_text(f'#!/bin/sh\necho "browser $1" >> "{self.log}"\n{life}\n')
        for f in [*bin_dir.iterdir(), browser]:
            f.chmod(0o755)
        (root / "upstart").mkdir()
        (root / "input").mkdir()
        os.mkfifo(root / "input" / "event1")
        (root / "devices").write_text(devices)
        (root / "state").mkdir()
        self.env = {
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "GAFFER_BROWSER": str(browser),
            "GAFFER_INPUT_DEVICES": str(root / "devices"),
            "GAFFER_INPUT_DIR": str(root / "input"),
            "GAFFER_UPSTART_DIR": str(root / "upstart"),
            "GAFFER_STATE_DIR": str(root / "state"),
        }
        self.proc: subprocess.Popen[bytes] | None = None

    def launch(self) -> subprocess.Popen[bytes]:
        self.proc = subprocess.Popen([SHELL, str(KINDLE / "gaffer_remote.sh")], env=self.env,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return self.proc

    def lines(self) -> list[str]:
        return self.log.read_text().splitlines()

    def wait_for(self, line: str, seconds: float = 15) -> None:
        deadline = time.monotonic() + seconds
        while line not in self.lines():
            if time.monotonic() > deadline:
                raise AssertionError(f"{line!r} never happened. Log: {self.lines()}")
            time.sleep(0.05)

    def press_power(self) -> None:
        with open(self.root / "input" / "event1", "wb") as pipe:
            pipe.write(_press())

    def close(self) -> None:
        if self.proc and self.proc.poll() is None:
            os.killpg(self.proc.pid, 9)
        subprocess.run(["pkill", "-f", str(self.root)], check=False)


def _new(tmp_path: Path, **kwargs) -> Kindle:
    root = tmp_path / "kindle"
    root.mkdir()
    return Kindle(root, **kwargs)


def test_one_power_press_gives_the_kindle_back(tmp_path: Path) -> None:
    k = _new(tmp_path)
    try:
        proc = k.launch()
        k.wait_for("browser http://192.168.1.20:54342/kindle")
        assert "lipc-set-prop com.lab126.powerd preventScreenSaver 1" in k.lines()
        assert "stop lab126_gui" in k.lines()
        assert "start lab126_gui" not in k.lines()

        k.press_power()
        assert proc.wait(timeout=15) == 0
        log = k.lines()
        assert log.index("lipc-set-prop com.lab126.powerd preventScreenSaver 0") < log.index("start lab126_gui")
        assert not (k.root / "state" / "gaffer_remote.pid").exists()
    finally:
        k.close()


def test_a_browser_that_closes_gives_the_kindle_back_with_no_press(tmp_path: Path) -> None:
    k = _new(tmp_path, browser_seconds=1)
    try:
        proc = k.launch()
        assert proc.wait(timeout=15) == 0
        assert "start lab126_gui" in k.lines()
        assert "lipc-set-prop com.lab126.powerd preventScreenSaver 0" in k.lines()
    finally:
        k.close()


def test_with_no_power_button_to_read_it_never_stops_the_kindle_screens(tmp_path: Path) -> None:
    k = _new(tmp_path, devices='N: Name="cyttsp5_mt"\nH: Handlers=event2\n')
    (k.root / "input" / "event1").unlink()  # the fallback device is not there either
    try:
        proc = k.launch()
        assert proc.wait(timeout=15) == 1
        assert "stop lab126_gui" not in k.lines()
        assert not any(line.startswith("browser ") for line in k.lines())
    finally:
        k.close()


def test_the_stop_scriptlet_closes_a_running_remote(tmp_path: Path) -> None:
    k = _new(tmp_path)
    try:
        proc = k.launch()
        k.wait_for("browser http://192.168.1.20:54342/kindle")
        subprocess.run([SHELL, str(KINDLE / "gaffer_remote_stop.sh")], env=k.env, check=True, timeout=15)
        assert proc.wait(timeout=15) == 0
        assert k.lines().count("start lab126_gui") == 1
        assert "lipc-set-prop com.lab126.powerd preventScreenSaver 0" in k.lines()
    finally:
        k.close()
