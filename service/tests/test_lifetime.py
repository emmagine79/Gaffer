"""The studio stops when its console window closes."""

from __future__ import annotations

import threading

from lumen_studio.lifetime import watch_console


def test_no_console_means_no_watcher():
    assert watch_console(lambda: None, hwnd=0) is None


def test_closing_the_window_stops_cleanly_then_forces_exit():
    alive = {"open": True}
    stopped = threading.Event()
    exited: list[int] = []
    thread = watch_console(
        stopped.set,
        hwnd=1234,
        exists=lambda _h: alive["open"],
        poll=0.01,
        grace=0.05,
        hard_exit=exited.append,
    )
    assert thread is not None and not stopped.wait(0.1)  # still open: nothing happens
    alive["open"] = False  # the user closes the window
    assert stopped.wait(1.0)
    thread.join(1.0)
    assert exited == [0]


def test_only_the_expected_beacon_warning_is_hidden():
    import logging

    from lumen_studio.__main__ import _QuietExpectedNoise

    quiet = _QuietExpectedNoise()
    record = lambda msg: logging.LogRecord("godox_mesh_bt.controller", logging.WARNING, __file__, 1, msg, None, None)
    assert not quiet.filter(record("no beacon received from device; proceeding without beacon echo"))
    assert quiet.filter(record("beacon network ID %s does not match our key (ours: %s) — wrong provisioning key!"))
