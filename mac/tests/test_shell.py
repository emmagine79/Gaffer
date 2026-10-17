"""Acceptance tests for SPEC-016: the Mac shell's menu bar, panel, window and shortcuts.

Build first: scripts/build_app.sh --no-install
Run:        uv run --project service --frozen pytest mac/tests/test_shell.py

Each test copies the shell from dist/Gaffer.app into a folder whose path has a space, reaches it
through a symlink, gives the copy its own bundle id (so Gaffer's real saved
settings are never touched), and swaps the bundled Python for a launcher that runs
standin_service.py, a small service that speaks contracts/api.md. The real shell
binary runs against it. Nothing here touches Bluetooth or a real light.

These need the desktop: the tests read the menu bar through Accessibility and press
keys with System Events, so the app that runs pytest must be allowed to control the
computer. They bring Finder to the front for a moment.
"""

from __future__ import annotations

import json
import os
import plistlib
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

import pytest
from test_app import BUILT_APP, WAIT_SECONDS, alive, pids_matching, run, wait_for

pytestmark = pytest.mark.skipif(not BUILT_APP.exists(), reason="build dist/Gaffer.app first")

STANDIN = Path(__file__).with_name("standin_service.py")
KEY_CODES = {"1": 18, "2": 19, "0": 29, "space": 49}
# The card says the title changes "within a second" of a look being applied.
TITLE_WITHIN_SECONDS = 1.0
SHORTCUT_SOURCE = Path(__file__).parents[1] / "Sources" / "Shortcuts.swift"
STORE_CHECK = Path(__file__).with_name("shortcut_store_check.swift")


def trash(path: Path) -> None:
    """Captain's rule: nothing is deleted, only moved to the Trash."""
    if path.exists():
        trash_dir = Path.home() / ".Trash"
        trash_dir.mkdir(exist_ok=True)
        shutil.move(str(path), str(trash_dir / f"{path.name}-{uuid.uuid4().hex[:8]}"))


class Shell:
    def __init__(self, app: Path, bundle_id: str, gaffer: int, info: dict):
        self.app, self.bundle_id, self.gaffer = app, bundle_id, gaffer
        self.child, self.port, self.secret = info["pid"], info["port"], info["secret"]

    def api(self, method: str, path: str):
        """Call the stand-in the way the web page does: with the session cookie."""
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method,
                                     data=b"" if method == "POST" else None)
        req.add_header("Cookie", f"gaffer_session={self.secret}")
        with urllib.request.urlopen(req, timeout=WAIT_SECONDS) as r:
            return json.loads(r.read())

    def state(self) -> dict:
        return self.api("GET", "/test/state")

    def title(self) -> str:
        """The text next to the icon in the menu bar, read from the Accessibility tree."""
        script = (f'tell application "System Events" to tell (first process whose unix id is {self.gaffer}) '
                  "to get title of every menu bar item of menu bar 2")
        out = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
        assert out.returncode == 0, f"could not read the menu bar: {out.stderr.strip()}"
        return out.stdout.strip()

    def wait_title(self, expected: str) -> None:
        """Wait until the menu bar shows `expected`."""
        start = time.monotonic()
        while time.monotonic() - start < WAIT_SECONDS:
            if self.title() == expected:
                return
        raise AssertionError(f"menu bar title is {self.title()!r}, wanted {expected!r}")


def press(key: str) -> None:
    """Press Control-Option-<key> as a person would."""
    subprocess.run(["osascript", "-e", f'tell application "System Events" to key code {KEY_CODES[key]} '
                    "using {control down, option down}"], check=True)


def frontmost() -> str:
    return run("osascript", "-e", 'tell application "System Events" to get name of first process whose frontmost is true').strip()


def frontmost_bundle() -> str:
    """Bundle id of the app in front. System Events' own answer never names a menu-bar-only app like Gaffer."""
    asn = run("lsappinfo", "front").strip()
    info = run("lsappinfo", "info", "-only", "bundleid", asn)
    assert 'bundleID="' in info, f"lsappinfo printed no bundle id (format changed?): {info!r}"
    return info.split('bundleID="')[1].split('"')[0]


def tell_gaffer(shell: Shell, script: str) -> str:
    """Run AppleScript inside `tell <the Gaffer copy>` through System Events and return what it prints."""
    full = f'tell application "System Events" to tell (first process whose unix id is {shell.gaffer})\n{script}\nend tell'
    out = subprocess.run(["osascript", "-e", full], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr.strip()
    return out.stdout.strip()


def bring_to_front(shell: Shell) -> None:
    tell_gaffer(shell, "set frontmost to true")
    wait_for(lambda: frontmost_bundle() == shell.bundle_id, "Gaffer to come to the front")


def launch(tmp: Path, *open_args: str, saved_settings: dict | None = None) -> Shell:
    real = tmp / "path with space" / "real"
    real.mkdir(parents=True)
    copy = real / "Gaffer.app"
    # Only the shell goes into the copy (binary, plist, icon). The bundled Python and web
    # build are big, and macOS checks every file of a new app on its first launch, which
    # made start-up slower than the tests' wait. The stand-in replaces the service anyway.
    (copy / "Contents/Resources/python/bin").mkdir(parents=True)
    subprocess.run(["ditto", str(BUILT_APP / "Contents/MacOS"), str(copy / "Contents/MacOS")], check=True)
    shutil.copy(BUILT_APP / "Contents/Info.plist", copy / "Contents/Info.plist")
    for icon in (BUILT_APP / "Contents/Resources").glob("*.icns"):
        shutil.copy(icon, copy / "Contents/Resources" / icon.name)
    (tmp / "link").symlink_to(real)
    app = tmp / "link" / "Gaffer.app"

    bundle_id = f"work.awelahlayray.gaffer.test{uuid.uuid4().hex[:8]}"
    plist = copy / "Contents/Info.plist"
    info = plistlib.loads(plist.read_bytes())
    info["CFBundleIdentifier"] = bundle_id
    plist.write_bytes(plistlib.dumps(info))
    state_file = tmp / "standin.json"
    # -I -S below: the stand-in uses only the standard library.
    launcher = copy / "Contents/Resources/python/bin/python3.14"
    # The stand-in and its Python live outside ~/Documents. A process Gaffer starts is
    # checked by macOS against Gaffer's permissions, and a new app copy reading Documents
    # would wait on a permission prompt. sys.base_prefix is the plain Python the venv uses.
    standin = tmp / "standin_service.py"
    shutil.copy(STANDIN, standin)
    python = Path(sys.base_prefix) / "bin" / f"python{sys.version_info.major}.{sys.version_info.minor}"
    launcher.write_text(f'#!/bin/sh\nexec "{python}" -I -S "{standin}" --state-file "{state_file}" "$@"\n')
    launcher.chmod(0o755)
    subprocess.run(["codesign", "--force", "--sign", "-", "--identifier", bundle_id, str(copy)],
                   check=True, capture_output=True)

    if saved_settings:  # what an earlier run, or a hand edit, left in this copy's own settings
        subprocess.run(["defaults", "import", bundle_id, "-"], input=plistlib.dumps(saved_settings), check=True)

    subprocess.run(["open", "-n", "-g", str(app), *(["--args", *open_args] if open_args else [])], check=True)
    pattern = f"{tmp.parent.name}/{tmp.name}/.*Gaffer.app/Contents/MacOS/Gaffer"
    gaffer = wait_for(lambda: (lambda f: f[0] if len(f) == 1 else None)(pids_matching(pattern)), "Gaffer to start")

    def ready():
        try:
            return json.loads(state_file.read_text())
        except (FileNotFoundError, ValueError):
            return None

    shell = Shell(app, bundle_id, gaffer, wait_for(ready, "the stand-in service to start"))
    # Wait until the shell's own socket and both web views are connected.
    wait_for(lambda: shell.state()["clients"] >= 3 and {"menubar", "window"} <= shell.state()["reports"].keys(),
             "the shell and both views to connect")
    return shell


def stop(shell: Shell) -> None:
    if alive(shell.gaffer):
        os.kill(shell.gaffer, signal.SIGKILL)
    try:
        wait_for(lambda: not alive(shell.child), "the stand-in service to exit")
    finally:
        if alive(shell.child):
            os.kill(shell.child, signal.SIGKILL)
        subprocess.run(["defaults", "delete", shell.bundle_id], capture_output=True)
        for folder in ("Caches", "WebKit", "HTTPStorages"):
            trash(Path.home() / "Library" / folder / shell.bundle_id)


@pytest.fixture
def shell(tmp_path):
    # A Gaffer already running would hold the same shortcuts; the test can't tell whose fired.
    assert not pids_matching("Gaffer.app/Contents/MacOS/Gaffer"), "quit every running Gaffer first"
    launched = launch(tmp_path)
    yield launched
    stop(launched)


def test_menu_bar_title_follows_the_look_applied_from_the_web_page(shell):
    """Criterion 1: the menu-bar title changes within a second when a look is applied.

    Measured from the apply to the first read that shows the new title, less the cost of one
    read (timed in this run), because the title can have changed at any point inside that read.
    """
    assert shell.title() == ""  # no look yet: icon only
    costs = []
    for _ in range(3):
        began = time.monotonic()
        shell.title()
        costs.append(time.monotonic() - began)
    read_cost = sorted(costs)[1]
    for look_id, name in (("interview", "Interview"), ("sunset", "Sunset")):
        began = time.monotonic()
        shell.api("POST", f"/api/looks/{look_id}/apply")  # what the web page does
        shell.wait_title(name)
        assert time.monotonic() - began - read_cost <= TITLE_WITHIN_SECONDS


def test_menu_bar_recovers_when_the_socket_drops(shell):
    """Checklist 5 and 8: when the service closes the socket, the shell reconnects by itself."""
    shell.api("POST", "/api/looks/interview/apply")
    shell.wait_title("Interview")
    opened = shell.state()["ws_opened"]
    shell.api("GET", "/test/drop-ws")
    # Only the shell reconnects (the demo pages don't), so one new socket is the shell's.
    wait_for(lambda: shell.state()["ws_opened"] == opened + 1, "the shell to reconnect")
    shell.wait_title("Interview")


def test_a_global_shortcut_works_while_another_app_is_frontmost(shell):
    """Criterion 2: shortcuts apply a look, turn every light off and step the cue from any app."""
    subprocess.run(["osascript", "-e", 'tell application "Finder" to activate'], check=True)
    wait_for(lambda: frontmost() == "Finder", "Finder to come to the front")

    press("2")  # Look 2 is the second look in GET /api/looks
    shell.wait_title("Interview")
    assert shell.state()["lights"] == {"key": True, "fill": True, "back": True}

    press("0")  # All off
    shell.wait_title("")
    assert shell.state()["lights"] == {"key": False, "fill": False, "back": False}

    press("space")  # Next cue: the first look of the cue list
    shell.wait_title("Talking head")
    assert frontmost_bundle() != shell.bundle_id, "a global shortcut must not pull Gaffer to the front"


def test_panel_and_window_are_live_views_of_the_same_service(shell):
    """Criterion 3: both views signed in, each on its own surface, and both follow the service."""
    first = shell.state()["calls"]
    pages = {c["query"] for c in first if c.get("page")}
    assert {"surface=menubar", "surface=window"} <= pages
    shell.api("POST", "/api/looks/sunset/apply")
    wait_for(lambda: all(shell.state()["reports"][s]["name"] == "Sunset" for s in ("menubar", "window")),
             "both views to show the new look")


def test_the_shell_never_links_core_bluetooth():
    """Criterion 4: only the Python service uses Bluetooth."""
    linked = run("otool", "-L", str(BUILT_APP / "Contents/MacOS/Gaffer"))
    assert "AppKit" in linked and "WebKit" in linked  # the command read the right file
    assert "CoreBluetooth" not in linked


@pytest.mark.parametrize("saved", [
    {"keyCode": 5_000_000_000, "modifiers": 5_000_000_000, "label": "x"},  # a number no key code can be
    {"keyCode": 0, "modifiers": 0, "label": "A"},  # a bare key, which would take over typing the letter
], ids=["number-out-of-range", "no-modifier-key"])
def test_a_bad_saved_shortcut_falls_back_to_the_default_key(tmp_path, saved):
    """A hand-edited or damaged setting must not crash a launch or grab a plain key."""
    launched = launch(tmp_path, saved_settings={"shortcuts.v1": {"look1": saved}})  # waits for the shell to come up
    try:
        assert alive(launched.gaffer)
        press("1")  # Look 1: back to Control-Option-1
        launched.wait_title("Talking head")
    finally:
        stop(launched)


def test_closing_settings_while_recording_leaves_the_shortcuts_working(shell):
    """Closing Settings mid-recording must give every global shortcut back (a shoot needs All off)."""
    bring_to_front(shell)
    tell_gaffer(shell, 'keystroke "," using command down')  # Settings
    wait_for(lambda: "Gaffer Settings" in tell_gaffer(shell, "get name of every window"), "Settings to open")
    tell_gaffer(shell, 'click button "⌃⌥2" of window "Gaffer Settings"')  # Look 2: start recording
    wait_for(lambda: "Press the keys" in tell_gaffer(shell, 'get name of every button of window "Gaffer Settings"'),
             "the button to start recording")
    tell_gaffer(shell, 'click (first button of window "Gaffer Settings" whose subrole is "AXCloseButton")')
    wait_for(lambda: "Gaffer Settings" not in tell_gaffer(shell, "get name of every window"), "Settings to close")

    press("2")  # Look 2 is Control-Option-2: Interview
    shell.wait_title("Interview")


def test_cut_copy_paste_and_select_all_work_in_the_web_view(shell):
    """The window is a web view: Cmd-A, Cmd-C and Cmd-V must work in its text boxes.

    This puts text on the clipboard; the test puts the old text back afterwards.
    """
    saved = subprocess.run(["pbpaste"], capture_output=True, text=True).stdout
    subprocess.run(["pbcopy"], input="sentinel", text=True, check=True)
    try:
        bring_to_front(shell)
        def window_has_the_keyboard():
            tell_gaffer(shell, 'perform action "AXRaise" of window "Gaffer"')  # make it the key window
            return shell.state()["reports"]["window"].get("focused")
        wait_for(window_has_the_keyboard, "the page's text box to have the keyboard")
        tell_gaffer(shell, 'keystroke "abc"')  # the page focuses its text box when it loads
        wait_for(lambda: shell.state()["reports"]["window"]["note"] == "abc", "the text box to take the typing")
        # One key at a time: the web view handles Select All in its own process, and a Cmd-C
        # sent at once would copy before the selection exists.
        for keys in ('keystroke "a" using command down', 'keystroke "c" using command down',
                     "key code 124", 'keystroke "v" using command down'):  # select all, copy, end, paste
            tell_gaffer(shell, keys)
            time.sleep(0.3)
        wait_for(lambda: shell.state()["reports"]["window"]["note"] == "abcabc", "Cmd-C then Cmd-V to repeat the text")
    finally:
        subprocess.run(["pbcopy"], input=saved, text=True)


def test_a_look_with_a_different_label_still_counts_as_the_same_shortcut(tmp_path):
    """Settings refuses a key combination another action holds, whatever label was saved with it."""
    work = tmp_path / "storecheck"
    work.mkdir()
    shutil.copy(STORE_CHECK, work / "main.swift")
    binary = work / "check"
    subprocess.run(["swiftc", "-O", "-swift-version", "5", str(SHORTCUT_SOURCE), str(work / "main.swift"),
                    "-o", str(binary)], check=True, capture_output=True, cwd=work)
    out = subprocess.run([str(binary)], capture_output=True, text=True, check=True, cwd=work)
    assert out.stdout.strip() == "Look 1"
