"""Start the light service on 127.0.0.1.

    python -m gaffer_service [--port N] [--session-from-stdin]

It prints one line, `GAFFER_SERVICE_READY port=N`, once it is listening. The Mac
app reads that line to know where to point its window.

With --session-from-stdin the first line of stdin is the session secret (see
session.py), and the service ends as soon as stdin reaches end of file. The Mac
app holds the other end of that pipe, and the kernel closes it when the app exits
for any reason, including a crash or SIGKILL. So the service can never outlive
Gaffer. Without the flag (for development) the service makes its own secret and
prints the sign-in link on stderr.

While running, the service records its port and secret in a file only this user
can read (session.runtime_file), so local tools and tests can reach it.
"""

from __future__ import annotations

import argparse
import logging
import os
import secrets
import socket
import sys
import threading

import uvicorn

from .app import create_app
from .session import protect, runtime_file, write_runtime_file


def _remove_runtime_file() -> None:
    runtime_file(os.getpid()).unlink(missing_ok=True)


def _exit_when_stdin_closes() -> None:
    def watch() -> None:
        try:
            while sys.stdin.buffer.read(4096):
                pass
        finally:
            _remove_runtime_file()
            os._exit(0)

    threading.Thread(target=watch, name="stdin-watch", daemon=True).start()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="gaffer_service")
    parser.add_argument("--port", type=int, default=0, help="TCP port on 127.0.0.1; 0 picks a free one")
    parser.add_argument("--session-from-stdin", action="store_true",
                        help="read the session secret from the first stdin line; exit when stdin closes")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    if args.session_from_stdin:
        secret = sys.stdin.buffer.readline().strip().decode("ascii", "replace")
        if not secret:
            sys.exit("gaffer_service: no session secret on stdin")
        _exit_when_stdin_closes()
    else:
        secret = secrets.token_urlsafe(32)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", args.port))
    sock.listen()
    port = sock.getsockname()[1]

    write_runtime_file(port, secret)
    # Removed on a normal shutdown (SIGTERM, SIGINT) here, and on stdin end of file by the watcher.
    app = create_app(on_shutdown=_remove_runtime_file)
    # No access log: the one-time sign-in link carries the secret in its query string.
    server = uvicorn.Server(uvicorn.Config(protect(app, secret), log_level="info", access_log=False))
    if not args.session_from_stdin:
        print(f"Sign in: http://127.0.0.1:{port}/session?key={secret}", file=sys.stderr, flush=True)
    print(f"GAFFER_SERVICE_READY port={port}", flush=True)
    server.run(sockets=[sock])


if __name__ == "__main__":
    main()
