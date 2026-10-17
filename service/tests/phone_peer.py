"""Test-only: makes a request to the real gate come from a phone's address. Shared by test_phone_access.py and
the Playwright launcher web/tests/phone_service_main.py. It is not part of the service and ships in no app.

A test on one machine can only reach the service from loopback, and since SPEC-024 the gate treats loopback as the
Mac window and nothing else. This stands in for the network: a request that names a host other than this Mac's own
arrives from ``address``, as a phone's would. The Mac's own hosts are the gate's (``guard.LOCAL_HOSTS``) and the Host
is read the gate's way (``guard.hostname``), so a change to what the gate calls the Mac cannot leave this behind.
"""

from gaffer.guard import LOCAL_HOSTS, hostname

PHONE_PORT = 50000


def as_if_from_phone(app, address: str):
    async def from_the_network(scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            host = hostname(dict(scope["headers"]).get(b"host", b"").decode())
            if host not in LOCAL_HOSTS:
                scope = {**scope, "client": (address, PHONE_PORT)}
        await app(scope, receive, send)

    return from_the_network
