"""Test-only launcher for the phone access e2e tests. It is not part of the service and ships in no app.

Since SPEC-024 the gate refuses a connection from loopback that names any host but 127.0.0.1 or
localhost, because a proxy on the Mac (`tailscale serve`, `ssh -L`) connects that way for visitors who
could be anywhere. A browser test on one machine can only ever connect from loopback, so a phone cannot
be played by a real connection here. Reaching the Mac's own Wi-Fi address instead would raise a macOS
network prompt.

So this launcher runs the real service, unchanged, and adds one layer in front of the real gate: a
request that names a host other than this Mac's own arrives from PHONE_ADDRESS, as a phone's would
(100.101.102.103 is in Tailscale's 100.64.0.0/10 range). The gate, the PIN, the cookies and the Host
checks are all the real ones. The Mac window names 127.0.0.1 and stays a loopback connection.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "service" / "tests"))

from gaffer import __main__ as service  # noqa: E402
from phone_peer import as_if_from_phone  # noqa: E402

PHONE_ADDRESS = "100.101.102.103"

real_protect = service.protect


def protect(app, secret, phone=None):
    return as_if_from_phone(real_protect(app, secret, phone), PHONE_ADDRESS)


service.protect = protect

if __name__ == "__main__":
    service.main()
