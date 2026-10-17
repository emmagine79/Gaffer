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

from gaffer import __main__ as service

PHONE_ADDRESS = "100.101.102.103"
MAC_HOSTS = {"127.0.0.1", "localhost", "::1"}

real_protect = service.protect


def protect(app, secret, phone=None):
    gate = real_protect(app, secret, phone)

    async def from_the_network(scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            host = dict(scope["headers"]).get(b"host", b"").decode().rsplit(":", 1)[0].strip("[]")
            if host not in MAC_HOSTS:
                scope = {**scope, "client": (PHONE_ADDRESS, 50000)}
        await gate(scope, receive, send)

    return from_the_network


service.protect = protect

if __name__ == "__main__":
    service.main()
