"""Start the Gaffer light service on 127.0.0.1 (and on the network only when phone access is on).

    python -m gaffer [--port N] [--session-from-stdin] [--demo] [--data DIR]

It prints one line, `GAFFER_SERVICE_READY port=N`, once it is listening. The Mac
app reads that line to know where to point its window.

With --session-from-stdin the first line of stdin is the session secret (see
session.py), and the service stops when stdin reaches end of file: cleanly, so the
lights' last state is saved and the link let go, with a hard exit a few seconds later
as a backstop. The Mac app holds the other end of that pipe, and the kernel closes it
when the app exits for any reason, including a crash or SIGKILL. So the service can
never outlive Gaffer. Without the flag (for development) the service makes its own secret and
prints the sign-in link on stderr.

While running, the service records its port and secret in a file only this user
can read (session.runtime_file), so local tools and tests can reach it.

--demo runs simulated lights of every kind and starts no Bluetooth scan at all.
"""

from __future__ import annotations

import argparse
import logging
import os
import secrets
import socket
import sys
import threading
import time
from pathlib import Path

import uvicorn

from .app import create_app
from .hub import LINK_STOP_SECONDS
from .listener import guarded_config
from .paths import AlreadyRunning, data_home, hold_data_folder
from .phone import PhoneAccess, saved_port, wildcard_free
from .session import protect, runtime_file, write_runtime_file


class _QuietExpectedNoise(logging.Filter):
    """Drop log lines that describe normal behaviour of this light as a warning.

    The ML100R never sends a network beacon on connect, so the library's
    "no beacon received" warning appears on every start and means nothing.
    Its other warnings, such as a beacon from the wrong network, still show.
    """

    EXPECTED = ("no beacon received from device",)

    def filter(self, record: logging.LogRecord) -> bool:
        return not str(record.msg).startswith(self.EXPECTED)


#: After uvicorn asks open requests and sockets to close, they get this long before it cancels
#: them, so a hung one can't hold the stop. Measured 18 Oct 2026 (demo lights, one open
#: socket): they closed within uvicorn's own 0.1 s pause. A stop with nothing hung never
#: reaches this limit, so uvicorn logs no "graceful shutdown exceeded" error.
CONNECTIONS_SECONDS = 1.0
#: Hub.stop saves the lights' state first, then gives the link LINK_STOP_SECONDS to let go of
#: the light. Everything else from stdin's end of file to exit (uvicorn's loop tick and pause,
#: the save, cancelling the hub's tasks, interpreter exit) measured 0.3 s on 18 Oct 2026.
SAVE_AND_EXIT_SECONDS = 1.0
BACKSTOP_SECONDS = CONNECTIONS_SECONDS + LINK_STOP_SECONDS + SAVE_AND_EXIT_SECONDS


def _remove_runtime_file() -> None:
    runtime_file(os.getpid()).unlink(missing_ok=True)


def _stop_when_stdin_closes(server: uvicorn.Server) -> None:
    """Stop cleanly once stdin closes, so the hub saves the lights' state and drops the link.

    A hard exit after BACKSTOP_SECONDS is the backstop: the service must never outlive
    Gaffer holding a light's only Bluetooth connection.
    """

    def watch() -> None:
        try:
            while sys.stdin.buffer.read(4096):
                pass
        finally:
            server.should_exit = True
            time.sleep(BACKSTOP_SECONDS)
            _remove_runtime_file()
            os._exit(0)

    threading.Thread(target=watch, name="stdin-watch", daemon=True).start()


def _version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("gaffer-service")
    except PackageNotFoundError:
        return "dev"


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


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="gaffer", description="Gaffer light service")
    parser.add_argument("--data", type=Path, default=None, help="where lights, keys, scenes and settings live")
    parser.add_argument("--port", type=int, default=int(os.environ.get("GAFFER_PORT") or 0),
                        help="TCP port on 127.0.0.1; 0 picks a free one")
    parser.add_argument("--session-from-stdin", action="store_true",
                        help="read the session secret from the first stdin line; exit when stdin closes")
    parser.add_argument("--demo", action="store_true", help="simulated lights of every kind; no Bluetooth needed")
    parser.add_argument("--import-keys", type=Path, metavar="FILE",
                        help="save a light paired elsewhere, from its mesh_state.json, then start")
    parser.add_argument("--address", default="", help="with --import-keys: the light's Bluetooth address")
    parser.add_argument("--name", default="", help="with --import-keys: what to call the light")
    parser.add_argument("--model", default="", help="with --import-keys: its model id, if it does not say")
    parser.add_argument("--self-test", action="store_true",
                        help="check the installation (no Bluetooth needed, your data untouched) and exit")
    parser.add_argument("--version", action="version", version=f"Gaffer {_version()}")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        from .selftest import main as self_test

        raise SystemExit(self_test())
    if args.data is None:
        args.data = data_home() / "demo" if args.demo else data_home()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, stream=sys.stderr,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logging.getLogger("godox_mesh_bt.controller").addFilter(_QuietExpectedNoise())
    if args.session_from_stdin:
        secret = sys.stdin.buffer.readline().strip().decode("ascii", "replace")
        if not secret:
            sys.exit("gaffer: no session secret on stdin")
    else:
        secret = secrets.token_urlsafe(32)

    try:
        lock = hold_data_folder(args.data)  # noqa: F841 - held until the process exits
    except AlreadyRunning:
        sys.exit("gaffer: another Gaffer service is already using this data folder. Quit it first.")
    if args.import_keys is not None:
        _import_keys(args, parser)

    phone_file = Path(args.data) / "phone.json"
    # With phone access left on, take the same port again so phones keep the address they have
    # (Captain, 18 Oct 2026). If it is taken now, on 127.0.0.1 or on every network address (which is
    # where phone access listens, and which a 127.0.0.1 bind does not show), any free port: phone
    # access shows the new address.
    previous = None if args.port else saved_port(phone_file)
    wanted = [args.port] if args.port else ([previous] if previous and wildcard_free(previous) else []) + [0]
    for index, port_choice in enumerate(wanted):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port_choice))
            break
        except OSError:
            sock.close()
            if index == len(wanted) - 1:
                raise
    sock.listen()
    port = sock.getsockname()[1]

    write_runtime_file(port, secret)
    # Removed on every clean shutdown (SIGTERM, SIGINT, stdin end of file), and by the watcher's backstop.
    # Phone access (SPEC-015) is switched on from the Mac window, and only then does the service listen
    # beyond 127.0.0.1. Once on, it stays on with the same PIN across restarts until switched off
    # (Captain, 18 Oct 2026), so it is kept in the data folder.
    phone = PhoneAccess(port=port, saved=phone_file)
    app = create_app(demo=args.demo, data_dir=args.data, on_shutdown=_remove_runtime_file, phone=phone)
    guarded = protect(app, secret, phone)
    phone.bind_listener(guarded, CONNECTIONS_SECONDS)
    # No access log: the one-time sign-in link carries the secret in its query string.
    server = uvicorn.Server(guarded_config(guarded, log_level="info", access_log=False,
                                           timeout_graceful_shutdown=CONNECTIONS_SECONDS))
    if args.session_from_stdin:
        _stop_when_stdin_closes(server)  # an end of file that came earlier is seen at once
    else:
        print(f"Sign in: http://127.0.0.1:{port}/session?key={secret}", file=sys.stderr, flush=True)
    print(f"GAFFER_SERVICE_READY port={port}", flush=True)
    server.run(sockets=[sock])


if __name__ == "__main__":
    main()
