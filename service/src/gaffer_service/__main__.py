"""Start the light service on 127.0.0.1.

    python -m gaffer_service [--port N] [--exit-when-stdin-closes]

It prints one line, `GAFFER_SERVICE_READY port=N`, once it is listening. The Mac
app reads that line to know where to point its window.

With --exit-when-stdin-closes the service ends as soon as its stdin reaches end of
file. The Mac app holds the other end of that pipe, and the kernel closes it when
the app exits for any reason, including a crash or SIGKILL. So the service can
never outlive Gaffer.
"""

from __future__ import annotations

import argparse
import logging
import os
import socket
import sys
import threading

import uvicorn

from .app import create_app


def _exit_when_stdin_closes() -> None:
    def watch() -> None:
        try:
            while sys.stdin.buffer.read(4096):
                pass
        finally:
            os._exit(0)

    threading.Thread(target=watch, name="stdin-watch", daemon=True).start()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="gaffer_service")
    parser.add_argument("--port", type=int, default=0, help="TCP port on 127.0.0.1; 0 picks a free one")
    parser.add_argument("--exit-when-stdin-closes", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    if args.exit_when_stdin_closes:
        _exit_when_stdin_closes()

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", args.port))
    sock.listen()
    port = sock.getsockname()[1]

    server = uvicorn.Server(uvicorn.Config(create_app(), log_level="info"))
    print(f"GAFFER_SERVICE_READY port={port}", flush=True)
    server.run(sockets=[sock])


if __name__ == "__main__":
    main()
