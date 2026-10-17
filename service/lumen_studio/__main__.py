"""``uv run lumen``: start the studio and open it in the browser."""

from __future__ import annotations

import argparse
import logging
import os
import secrets
import socket
import threading
import webbrowser
from pathlib import Path

import uvicorn

from .app import create_app
from .lifetime import watch_console
from .paths import (
    AlreadyRunning,
    clear_runtime,
    data_home,
    hold_data_folder,
    read_runtime,
    write_runtime,
)
from .ports import DEFAULT_PORT, bind_free_port


class _QuietExpectedNoise(logging.Filter):
    """Drop log lines that describe normal behaviour of this light as a warning.

    The ML100R never sends a network beacon on connect, so the library's
    "no beacon received" warning appears on every start and means nothing.
    Its other warnings, such as a beacon from the wrong network, still show.
    """

    EXPECTED = ("no beacon received from device",)

    def filter(self, record: logging.LogRecord) -> bool:
        return not str(record.msg).startswith(self.EXPECTED)


def _version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("lumen-studio")
    except PackageNotFoundError:
        return "dev"


def _lan_ip() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def _import_keys(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    """Save a light paired elsewhere (the CLI, Home Assistant) into the library."""
    from godox_mesh_bt.state import MeshState

    from .catalog import model_caps
    from .lights import LightLibrary

    if not args.address:
        parser.error("--import-keys needs the light's Bluetooth address: --address AA:BB:CC:DD:EE:FF")
    try:
        state = MeshState.load(args.import_keys)
    except (OSError, ValueError, KeyError) as err:
        parser.error(f"cannot read {args.import_keys}: {err}")
    radio_id = (args.model or "").upper()
    if radio_id and not model_caps(radio_id).known:
        parser.error(f"{radio_id} is not a model in the catalogue")
    light = LightLibrary(args.data).import_keys(
        state, address=args.address, name=args.name or "", radio_id=radio_id,
        source="manual" if radio_id else "advert",
    )
    print(f"  Saved {light.name} ({light.address}) to {args.data}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="lumen", description="Lumen Studio: real-time control of Godox mesh lights")
    parser.add_argument("--data", type=Path, default=None, help="where lights, keys, scenes and settings live")
    parser.add_argument("--port", type=int, default=int(os.environ.get("LUMEN_PORT") or DEFAULT_PORT),
                        help="the port to serve on; when it is busy the next free one is used (default 8787)")
    parser.add_argument("--lan", action="store_true", help="also serve on the local network (token protected)")
    parser.add_argument("--demo", action="store_true", help="simulated lights of every kind; no Bluetooth needed")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--tie-to-console", action="store_true",
                        help="stop when the console window this was started from is closed (used by the launcher)")
    parser.add_argument("--import-keys", type=Path, metavar="FILE",
                        help="save a light paired elsewhere, from its mesh_state.json, then start")
    parser.add_argument("--address", default="", help="with --import-keys: the light's Bluetooth address")
    parser.add_argument("--name", default="", help="with --import-keys: what to call the light")
    parser.add_argument("--model", default="", help="with --import-keys: its model id, if it does not say")
    parser.add_argument("--self-test", action="store_true",
                        help="check the installation (no Bluetooth needed, your data untouched) and exit")
    parser.add_argument("--version", action="version", version=f"Lumen Studio {_version()}")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        from .selftest import main as self_test

        raise SystemExit(self_test())
    if args.data is None:
        args.data = data_home() / "demo" if args.demo else data_home()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("godox_mesh_bt.controller").addFilter(_QuietExpectedNoise())
    try:
        lock = hold_data_folder(args.data)  # noqa: F841 - held until the process exits
    except AlreadyRunning as err:
        running = read_runtime(args.data)
        if running is None:
            parser.exit(1, f"lumen: {err}. Close it first (its window, or the Start Lumen Studio launcher).\n")
        # One studio per data folder: point at the one that is running instead.
        print(f"\n  Lumen Studio is already running at {running['url']}\n")
        if not args.no_browser:
            webbrowser.open(running["url"])
        raise SystemExit(0) from None
    if args.import_keys is not None:
        _import_keys(args, parser)

    token = secrets.token_urlsafe(9) if args.lan else None
    host = "0.0.0.0" if args.lan else "127.0.0.1"
    try:
        sock, port = bind_free_port(host, args.port)
    except OSError as err:
        parser.exit(1, f"lumen: could not open any port to serve on: {err}\n")
    app = create_app(demo=args.demo, data_dir=args.data, token=token, hosts=(_lan_ip(),) if args.lan else ())

    local = f"http://127.0.0.1:{port}/" + (f"?t={token}" if token else "")
    moved = f"  (port {args.port} is busy, so {port} is used)" if port != args.port else ""
    print(f"\n  Lumen Studio{'  (demo lights)' if args.demo else ''}\n  {local}{moved}\n  data: {args.data}")
    if args.lan:
        print(f"  phone / LAN:  http://{_lan_ip()}:{port}/?t={token}")
    print()
    write_runtime(args.data, port=port, url=local)
    if not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(local)).start()
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    if args.tie_to_console:
        # Graceful first: uvicorn finishes, the hub disconnects from the lights.
        watch_console(lambda: setattr(server, "should_exit", True))
    try:
        server.run(sockets=[sock])
    finally:
        clear_runtime(args.data)


if __name__ == "__main__":
    main()
