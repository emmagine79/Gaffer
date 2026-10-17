"""Tie the studio's lifetime to the console window it was started from.

Closing a console window is supposed to end every program attached to it, but
how that signal arrives differs between the classic console and Windows
Terminal, and a console host that dies abruptly sends nothing at all: measured
on Windows 11, killing the host left the server running and holding the light's
only Bluetooth connection. So the server watches the window itself, and shuts
down cleanly the moment it is gone, with a hard exit as a backstop.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import threading
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)

POLL_SECONDS = 1.0
GRACE_SECONDS = 4.0


def console_window() -> int:
    """The handle of this process's console window, or 0 when there is none."""
    if sys.platform != "win32":
        return 0
    return int(ctypes.windll.kernel32.GetConsoleWindow() or 0)


def window_exists(hwnd: int) -> bool:
    return bool(ctypes.windll.user32.IsWindow(hwnd))


def watch_console(
    on_gone: Callable[[], None],
    *,
    hwnd: int | None = None,
    exists: Callable[[int], bool] = window_exists,
    poll: float = POLL_SECONDS,
    grace: float = GRACE_SECONDS,
    hard_exit: Callable[[int], None] = os._exit,
) -> threading.Thread | None:
    """Call ``on_gone`` once the console window closes; force-exit after ``grace``.

    Returns the watcher thread, or None when there is no console to watch.
    """
    handle = console_window() if hwnd is None else hwnd
    if not handle:
        logger.info("no console window to watch; lifetime is not tied")
        return None

    def run() -> None:
        while exists(handle):
            time.sleep(poll)
        logger.warning("console window closed; stopping Lumen Studio")
        on_gone()
        time.sleep(grace)
        hard_exit(0)  # a clean stop did not finish in time; never linger holding the light

    thread = threading.Thread(target=run, name="console-watch", daemon=True)
    thread.start()
    return thread
