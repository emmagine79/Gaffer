"""Where Lumen Studio keeps its files.

Mesh keys are live crypto material and scenes are personal, so neither lives
in the source tree: they go in the platform's per-user data folder, or wherever
``LUMEN_HOME`` points. The catalogue data the code reads ships inside the
package.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PACKAGE_DATA = Path(__file__).resolve().parent / "data"
LOCK_FILE = "studio.lock"
APP_DIR_NAME = "Lumen Studio"


def data_home(env: dict[str, str] | None = None, platform: str | None = None) -> Path:
    """The per-user folder for keys, lights, scenes and settings."""
    env = dict(os.environ) if env is None else env
    platform = sys.platform if platform is None else platform
    if env.get("LUMEN_HOME"):
        return Path(env["LUMEN_HOME"]).expanduser()
    home = Path(env.get("USERPROFILE") or env.get("HOME") or Path.home())
    if platform == "win32":
        return Path(env.get("APPDATA") or home / "AppData" / "Roaming") / APP_DIR_NAME
    if platform == "darwin":
        return home / "Library" / "Application Support" / APP_DIR_NAME
    return Path(env.get("XDG_DATA_HOME") or home / ".local" / "share") / "lumen-studio"


class AlreadyRunning(RuntimeError):
    """Another studio holds this data folder."""


def hold_data_folder(root: Path) -> object:
    """Lock ``root`` for this process; keep the returned handle alive while running.

    Two studios on one data folder would each reserve the same mesh sequence
    numbers, and the lights would drop one studio's commands as replays. The
    operating system releases the lock when the process ends, however it ends.
    """
    root.mkdir(parents=True, exist_ok=True)
    handle = open(root / LOCK_FILE, "a+")  # noqa: SIM115 - held open for the life of the process
    try:
        if sys.platform == "win32":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as err:
        handle.close()
        raise AlreadyRunning(f"another Lumen Studio is already using {root}") from err
    return handle


RUNTIME_FILE = "studio.json"


def write_runtime(root: Path, *, port: int, url: str) -> None:
    """Say where this studio is running, so launchers can find, open or replace it."""
    import json
    import time

    root.mkdir(parents=True, exist_ok=True)
    tmp = root / (RUNTIME_FILE + ".tmp")
    tmp.write_text(json.dumps({"pid": os.getpid(), "port": port, "url": url, "started": time.time()}), encoding="utf-8")
    os.replace(tmp, root / RUNTIME_FILE)


def read_runtime(root: Path) -> dict | None:
    """Where a studio said it was running, or None. It may have died since: callers check its health."""
    import json

    try:
        data = json.loads((root / RUNTIME_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("port"), int) else None


def clear_runtime(root: Path) -> None:
    try:
        (root / RUNTIME_FILE).unlink()
    except OSError:
        pass
