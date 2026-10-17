"""Acceptance tests for phone access (SPEC-015), through the real HTTP and WebSocket interface.

The phone is a client whose peer address is not loopback (192.168.1.50, a Wi-Fi address). The Mac
window is a loopback client, signed in with the launch secret. Both reach the same app through the
same guard. Demo mode, so no Bluetooth is touched. Tailscale is a fake script that prints
`tailscale status --json` output; the real tool is never run.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import socket
import stat
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from websockets.asyncio.client import connect

from gaffer.app import create_app
from gaffer.listener import guarded_config
from gaffer.phone import MAX_WRONG_GUESSES, PHONE_COOKIE, PIN_DIGITS, PhoneAccess
from gaffer.session import COOKIE, protect
from phone_peer import as_if_from_phone

SECRET = "test-secret-for-this-launch"
LAN = "192.168.1.20"  # the Mac's Wi-Fi address
PHONE = "192.168.1.50"  # the phone's
PORT = 8787
TAILNET_NAME = "studio-mac.tail1234.ts.net"
TAILNET_IP = "100.64.0.9"

RUNNING = {"BackendState": "Running", "Self": {"DNSName": f"{TAILNET_NAME}.", "TailscaleIPs": [TAILNET_IP, "fd7a:115c:a1e0::9"]}}
STOPPED = {"BackendState": "Stopped", "Self": {"DNSName": f"{TAILNET_NAME}.", "TailscaleIPs": []}}


def fake_tailscale(folder: Path, status: dict) -> str:
    """A script that prints `tailscale status --json` output, standing in for the real tool."""
    script = folder / "tailscale"
    script.write_text("#!/bin/sh\ncat <<'JSON'\n" + json.dumps(status) + "\nJSON\n")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return str(script)


class Studio:
    def __init__(self, phone: TestClient, mac: TestClient, access: PhoneAccess, guarded) -> None:
        self.phone, self.mac, self.access, self.guarded = phone, mac, access, guarded

    def client_at(self, address: str) -> TestClient:
        """Another phone, whose connection comes from ``address``, on the same event loop."""
        other = TestClient(self.guarded, base_url=f"http://{LAN}:{PORT}", client=(address, 50000))
        other.portal = self.phone.portal
        return other

    def switch_on(self) -> str:
        reply = self.mac.post("/api/phone", json={"enabled": True})
        assert reply.status_code == 200 and reply.json()["enabled"] is True
        assert self.mac.get("/api/phone?wait=1").json()["checking"] is False  # the Tailscale names are in
        return reply.json()["pin"]

    def sign_in(self, pin: str) -> httpx.Response:
        # A browser always sends Origin on a POST: the page's own address, which is the phone's Host.
        return self.phone.post("/api/session", json={"pin": pin}, headers={"origin": f"http://{LAN}:{PORT}"})

    def brightness(self) -> float:
        light = self.mac.get("/api/lights").json()["lights"][0]
        return light["state"]["brightness"]


@contextmanager
def studio_with(tmp_path: Path, cli: str | None):
    """The app behind the guard. The phone client is entered (it holds the app's life and the sockets);
    the Mac client only makes plain requests."""
    access = PhoneAccess(port=PORT, lan_ip=lambda: LAN, tailscale_cli=lambda: cli)
    app = create_app(demo=True, data_dir=tmp_path / "data", phone=access)
    guarded = protect(app, SECRET, access)
    with TestClient(guarded, base_url=f"http://{LAN}:{PORT}", client=(PHONE, 50000)) as phone:
        mac = TestClient(guarded, base_url=f"http://127.0.0.1:{PORT}")
        mac.portal = phone.portal  # one event loop for both, as in the service
        assert mac.get(f"/session?key={SECRET}", follow_redirects=False).status_code == 303
        assert mac.cookies.get(COOKIE) == SECRET
        yield Studio(phone, mac, access, guarded)


@pytest.fixture
def studio(tmp_path):
    with studio_with(tmp_path, fake_tailscale(tmp_path, RUNNING)) as s:
        yield s


def ws_url(host: str = LAN) -> str:
    return f"ws://{host}:{PORT}/ws"


def wait_for_state(ws, wanted) -> dict:
    """Read the socket until a state update satisfies ``wanted``."""
    for _ in range(300):
        message = ws.receive_json()
        if message.get("type") == "state" and wanted(message["state"]):
            return message["state"]
    raise AssertionError("the light never reached the wanted state")


def refused_socket(client: TestClient, url: str, **kwargs) -> int:
    with pytest.raises(WebSocketDisconnect) as refused, client.websocket_connect(url, **kwargs):
        pass
    return refused.value.code


def wrong_pin(pin: str) -> str:
    return "000000" if pin != "000000" else "000001"


def test_a_phone_without_the_pin_controls_nothing_and_with_it_controls_the_lights(studio):
    """SPEC AC7: no cookie means every route and the light socket refuse, and no light changes."""
    pin = studio.switch_on()
    assert len(pin) == PIN_DIGITS and pin.isdigit()
    before = studio.brightness()

    # Without the cookie: the page is the PIN screen (401), the API and every POST say 401, the socket never opens.
    assert studio.phone.get("/api/session").json()["error"] == "pin_required"
    for path in ("/api/lights", "/api/export", "/api/scan", "/api/models", "/scan"):
        assert studio.phone.get(path).status_code == 401, path
    for path in ("/api/phone", "/api/phone/pin", "/api/lights", "/api/anything/at/all"):
        reply = studio.phone.post(path, json={"enabled": False})
        assert reply.status_code == 401 and reply.json()["error"] == "pin_required", path
    assert refused_socket(studio.phone, ws_url()) == 4401
    assert studio.access.enabled is True and studio.brightness() == before

    # The right PIN gives a cookie, and then set, power and look.apply reach the light.
    reply = studio.sign_in(pin)
    assert reply.status_code == 200
    cookie = reply.headers["set-cookie"].lower()
    assert f"{PHONE_COOKIE}=" in cookie and "httponly" in cookie and "samesite=strict" in cookie
    assert studio.phone.get("/api/session").json() == {"signed_in": True, "local": False}
    with studio.phone.websocket_connect(ws_url()) as ws:
        light = ws.receive_json()["selected"]
        ws.send_json({"type": "set", "light": light, "patch": {"brightness": 17}})
        wait_for_state(ws, lambda s: s["brightness"] == 17)
        ws.send_json({"type": "power", "light": light, "on": False})
        wait_for_state(ws, lambda s: s["power"] is False)
        ws.send_json({"type": "look.apply", "light": light, "patch": {"brightness": 33, "power": True}})
        wait_for_state(ws, lambda s: s["brightness"] == 33)
    assert studio.brightness() == 33

    # A phone with the PIN still cannot read the PIN or change phone access: that is the Mac's.
    assert studio.phone.get("/api/phone").json()["error"] == "mac_only"
    assert studio.phone.post("/api/phone", json={"enabled": False}).json()["error"] == "mac_only"
    assert studio.access.enabled is True
    # The Mac window never needs the PIN, and its secret is no use to a phone.
    assert studio.mac.get("/api/lights").status_code == 200
    studio.phone.cookies.clear()
    studio.phone.cookies.set(COOKIE, SECRET)
    assert studio.phone.get("/api/lights").status_code == 401


def test_a_wrong_pin_is_refused(studio):
    pin = studio.switch_on()
    reply = studio.sign_in(wrong_pin(pin))
    assert reply.status_code == 401 and reply.json()["error"] == "wrong_pin"
    assert PHONE_COOKIE not in reply.headers.get("set-cookie", "")
    assert studio.phone.get("/api/lights").status_code == 401
    assert refused_socket(studio.phone, ws_url()) == 4401
    for not_a_pin in ("12345", "1234567", "abcdef", "١٢٣٤٥٦", None, 123456):  # wrong shape: refused, never signs in
        assert studio.sign_in(not_a_pin).status_code == 400
    assert studio.phone.post("/api/session", content=b"x" * 10_000).status_code == 400


def test_a_hundred_wrong_pins_lock_the_pin_until_new_pin(studio):
    """NIST SP 800-63B 5.2.2: at most 100 failed attempts. The 101st try with the right PIN is refused too."""
    pin = studio.switch_on()
    bad = wrong_pin(pin)
    replies = [studio.sign_in(bad) for _ in range(MAX_WRONG_GUESSES)]
    assert {r.status_code for r in replies[:-1]} == {401} and replies[-1].json()["error"] == "pin_locked"
    locked = studio.sign_in(pin)
    assert locked.status_code == 403 and locked.json()["error"] == "pin_locked"
    assert PHONE_COOKIE not in locked.headers.get("set-cookie", "")
    assert studio.mac.get("/api/phone").json()["locked"] is True

    fresh = studio.mac.post("/api/phone/pin", json={}).json()
    assert fresh["locked"] is False
    assert studio.sign_in(fresh["pin"]).status_code == 200


def test_new_pin_signs_every_phone_out_and_closes_its_socket(studio):
    pin = studio.switch_on()
    assert studio.sign_in(pin).status_code == 200
    with studio.phone.websocket_connect(ws_url()) as ws:
        ws.receive_json()
        new = studio.mac.post("/api/phone/pin", json={}).json()["pin"]
        with pytest.raises(WebSocketDisconnect) as closed:
            for _ in range(300):
                ws.receive_json()
        assert closed.value.code == 4401
    assert studio.phone.get("/api/lights").status_code == 401  # the old cookie is dead
    if new != pin:  # one time in a million the new PIN is the old one
        assert studio.sign_in(pin).status_code == 401
    assert studio.sign_in(new).status_code == 200


def test_phone_access_is_off_until_switched_on_and_off_again_cuts_phones_off(studio):
    # Off at launch: a phone gets nothing, not even the PIN screen.
    assert studio.mac.get("/api/phone").json() == {"enabled": False, "pin": None, "locked": False, "checking": False, "tailscale": None, "targets": []}
    for reply in (studio.phone.get("/"), studio.phone.get("/api/session"), studio.sign_in("123456")):
        assert reply.status_code == 403 and reply.json()["error"] == "phone_access_off"
    assert refused_socket(studio.phone, ws_url()) == 4403

    pin = studio.switch_on()
    assert studio.sign_in(pin).status_code == 200
    with studio.phone.websocket_connect(ws_url()) as ws:
        ws.receive_json()
        assert studio.mac.post("/api/phone", json={"enabled": False}).json()["enabled"] is False
        with pytest.raises(WebSocketDisconnect):
            for _ in range(300):
                ws.receive_json()
    assert studio.phone.get("/api/lights").status_code == 403

    # Switching on again makes a new PIN, and the phone's old cookie does not come back to life.
    again = studio.switch_on()
    assert studio.phone.get("/api/lights").status_code == 401
    assert studio.sign_in(again).status_code == 200


def test_host_and_origin_checks_still_apply_to_the_wifi_and_tailscale_names(studio):
    pin = studio.switch_on()
    # The Wi-Fi address, the Tailscale name and the Tailscale address reach the PIN screen. Anything else is 400.
    for host in (f"{LAN}:{PORT}", f"{TAILNET_NAME}:{PORT}", TAILNET_NAME, f"{TAILNET_IP}:{PORT}", f"[fd7a:115c:a1e0::9]:{PORT}"):
        assert studio.phone.get("/api/session", headers={"host": host}).status_code == 401, host
    for host in ("evil.example", "100.64.0.99", "192.168.1.99", "127.0.0.1", "localhost"):
        assert studio.phone.get("/api/session", headers={"host": host}).status_code == 400, host

    assert studio.sign_in(pin).status_code == 200
    assert studio.phone.get("/api/lights", headers={"host": "evil.example"}).status_code == 400  # a cookie does not excuse the Host
    assert studio.phone.get("/api/lights", headers={"host": TAILNET_NAME}).status_code == 200
    # A signed-in phone's socket still refuses another site's page, and takes its own.
    assert refused_socket(studio.phone, ws_url(), headers={"origin": "http://evil.example"}) == 4403
    with studio.phone.websocket_connect(ws_url(), headers={"origin": f"http://{LAN}:{PORT}"}) as ws:
        assert ws.receive_json()["type"] == "hello"
    # Another page open on the Mac cannot switch phone access, even with the Mac's cookie.
    reply = studio.mac.post("/api/phone", json={"enabled": False}, headers={"origin": "http://evil.example"})
    assert reply.status_code == 403 and studio.access.enabled is True


def test_the_mac_shows_a_wifi_code_and_a_tailscale_code_from_the_tailscale_tool(tmp_path):
    with studio_with(tmp_path, fake_tailscale(tmp_path, RUNNING)) as s:
        s.switch_on()
        status = s.mac.get("/api/phone").json()
        assert status["tailscale"] is True
        assert [(t["kind"], t["url"]) for t in status["targets"]] == [
            ("wifi", f"http://{LAN}:{PORT}/"), ("tailscale", f"http://{TAILNET_NAME}:{PORT}/")]
        assert all(t["qr"].startswith("data:image/svg+xml") for t in status["targets"])
    # No tool, or Tailscale not running: just the Wi-Fi code, and Tailscale names are not let in.
    for cli in (None, fake_tailscale(tmp_path, STOPPED)):
        with studio_with(tmp_path / "other", cli) as s:
            s.switch_on()
            status = s.mac.get("/api/phone").json()
            assert [t["kind"] for t in status["targets"]] == ["wifi"] and status["tailscale"] is False
            assert s.phone.get("/api/session", headers={"host": TAILNET_NAME}).status_code == 400


async def test_the_network_port_opens_only_while_phone_access_is_on(tmp_path):
    """The real second listener: closed at launch, open on a real socket while on, closed again after."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    access = PhoneAccess(port=port, lan_ip=lambda: LAN, tailscale_cli=lambda: fake_tailscale(tmp_path, RUNNING))
    app = create_app(demo=True, data_dir=tmp_path / "data", phone=access)
    guarded = protect(app, SECRET, access)
    access.bind_listener(as_if_from_phone(guarded, PHONE), 1.0)
    name = {"host": TAILNET_NAME}  # a phone names the Tailscale name; here it reaches this machine over loopback
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as web:
            with pytest.raises(httpx.ConnectError):
                await web.get("/api/session", headers=name)
            await access.enable()
            await access.settled()
            try:
                assert (await web.get("/api/session", headers=name)).json()["error"] == "pin_required"
                # A phone that resolves the Tailscale name to its IPv6 address reaches the same listener.
                async with httpx.AsyncClient(base_url=f"http://[::1]:{port}") as v6:
                    assert (await v6.get("/api/session", headers=name)).json()["error"] == "pin_required"
                assert (await web.post("/api/session", json={"pin": wrong_pin(access.pin)}, headers=name)).status_code == 401
                signed = await web.post("/api/session", json={"pin": access.pin}, headers=name)
                assert signed.status_code == 200
                async with _phone_socket(port, signed.cookies[PHONE_COOKIE]) as ws:
                    assert json.loads(await ws.recv())["type"] == "hello"
                    await access.disable()
                    with pytest.raises(Exception) as ended:
                        while True:
                            await ws.recv()
                    assert getattr(ended.value, "rcvd", None) is None or ended.value.rcvd.code == 4401
            finally:
                await access.disable()
            with pytest.raises(httpx.ConnectError):
                await web.get("/api/session", headers=name)


def _phone_socket(port: int, token: str):
    """A WebSocket to the real listener that names the Tailscale name as its Host, as a phone's browser would."""
    return connect(f"ws://{TAILNET_NAME}:{port}/ws", host="127.0.0.1", port=port, additional_headers={"Cookie": f"{PHONE_COOKIE}={token}"})


def test_only_connections_from_a_private_network_or_tailscale_get_as_far_as_the_pin(studio):
    """A public address is refused even with the right PIN and a Host the Mac listed: the Host header is
    whatever the sender writes, and the Mac's IPv6 address can be reachable from the internet."""
    pin = studio.switch_on()
    refused = ("8.8.8.8", "2001:4860::1", "::ffff:8.8.8.8", "100.128.0.1", "172.32.0.1", "192.169.0.1", "fec0::1")  # and loopback: see the SPEC-024 tests
    allowed = ("10.1.2.3", "172.16.0.9", "192.168.1.77", "169.254.3.4", "100.100.1.1", "::ffff:192.168.1.77",
               "fe80::1", "fd00::1", "fd7a:115c:a1e0::9")
    for address in refused:
        far = studio.client_at(address)
        reply = far.post("/api/session", json={"pin": pin})
        assert reply.status_code == 403 and reply.json()["error"] == "network_not_allowed", address
        assert PHONE_COOKIE not in reply.headers.get("set-cookie", ""), address
        assert far.get("/api/session").status_code == 403, address
        assert refused_socket(far, ws_url()) == 4403, address
    for address in allowed:
        assert studio.client_at(address).get("/api/session").json()["error"] == "pin_required", address
    # A signed-in phone's cookie is no use from a public address either.
    token = studio.sign_in(pin).cookies[PHONE_COOKIE]
    far = studio.client_at("8.8.8.8")
    far.cookies.set(PHONE_COOKIE, token)
    assert far.get("/api/lights").status_code == 403
    assert studio.phone.get("/api/lights").status_code == 200


LOOPBACK_PEERS = ("127.0.0.1", "::1", "127.0.0.2", "::ffff:127.0.0.1")  # plain, IPv6, anywhere in 127/8, IPv4-mapped
FORWARDING_HEADERS = ({"x-forwarded-for": "192.168.1.50"}, {"x-forwarded-host": TAILNET_NAME}, {"forwarded": "for=192.168.1.50"},
                      {"tailscale-user-login": "phone@example.com"}, {"tailscale-user-name": "Phone"})


def test_a_loopback_peer_that_names_the_tailnet_or_the_lan_is_refused_with_or_without_a_cookie(studio):
    """SPEC-024: `tailscale serve`, `ssh -L` and dev proxies forward from 127.0.0.1 and keep the visitor's Host.
    Loopback means the Mac window, and only when the Host is 127.0.0.1 or localhost."""
    pin = studio.switch_on()
    token = studio.sign_in(pin).cookies[PHONE_COOKIE]
    for peer in LOOPBACK_PEERS:
        proxy = TestClient(studio.guarded, base_url=f"http://{LAN}:{PORT}", client=(peer, 50000))
        proxy.portal = studio.phone.portal
        for host in (f"{TAILNET_NAME}:{PORT}", TAILNET_NAME, f"{LAN}:{PORT}", f"{TAILNET_IP}:{PORT}", f"[fd7a:115c:a1e0::9]:{PORT}"):
            where = (peer, host)
            reply = proxy.get("/api/session", headers={"host": host})  # no cookie
            assert reply.status_code == 403 and reply.json()["error"] == "network_not_allowed", where
            assert proxy.post("/api/session", json={"pin": pin}, headers={"host": host, "origin": f"http://{host}"}).status_code == 403, where
            assert refused_socket(proxy, f"ws://{host}/ws", headers={"host": host}) == 4403, where
            proxy.cookies.set(PHONE_COOKIE, token)  # a phone's cookie is no use through a proxy either
            reply = proxy.get("/api/lights", headers={"host": host})
            assert reply.status_code == 403 and reply.json()["error"] == "network_not_allowed", where
            proxy.cookies.set(COOKIE, SECRET)  # and neither is the Mac window's
            assert proxy.get("/api/lights", headers={"host": host}).status_code == 403, where
            proxy.cookies.clear()
    # The Mac window is untouched: loopback naming 127.0.0.1 or localhost.
    for host in (f"127.0.0.1:{PORT}", f"localhost:{PORT}"):
        assert studio.mac.get("/api/lights", headers={"host": host}).status_code == 200, host


def test_a_loopback_request_with_forwarding_headers_is_refused(studio):
    """SPEC-024: a proxy on this Mac says who it forwards for. A loopback connection that carries X-Forwarded-*,
    Forwarded or Tailscale-* headers is not the Mac window, whatever Host it names and whatever cookie it holds."""
    pin = studio.switch_on()
    token = studio.sign_in(pin).cookies[PHONE_COOKIE]
    for headers in FORWARDING_HEADERS:
        for host in (f"{TAILNET_NAME}:{PORT}", f"{LAN}:{PORT}", f"127.0.0.1:{PORT}"):
            where = (headers, host)
            for cookies in ({}, {PHONE_COOKIE: token}, {COOKIE: SECRET}):
                proxy = TestClient(studio.guarded, base_url=f"http://{host}", client=("127.0.0.1", 50000), cookies=cookies)
                proxy.portal = studio.phone.portal
                reply = proxy.get("/api/lights", headers=headers)
                assert reply.status_code == 403 and reply.json()["error"] == "network_not_allowed", (where, cookies)
                assert refused_socket(proxy, f"ws://{host}/ws", headers=headers) == 4403, (where, cookies)
    # The same request from a phone's own address is not a loopback request: the PIN decides.
    phone = studio.client_at(PHONE)
    assert phone.get("/api/session", headers={"x-forwarded-for": "192.168.1.50"}).json()["error"] == "pin_required"


def test_a_proxy_that_sends_no_header_the_gate_knows_still_needs_the_launch_secret(studio):
    """SPEC-024, the limit of the header check: a proxy on this Mac that sends no forwarding header we list
    (here X-Real-IP) and rewrites Host to 127.0.0.1 looks like the Mac window. The launch secret cookie is what
    stops its visitor, and the contract says so."""
    studio.switch_on()
    proxy = TestClient(studio.guarded, base_url=f"http://127.0.0.1:{PORT}", client=("127.0.0.1", 50000))
    proxy.portal = studio.phone.portal
    headers = {"x-real-ip": "203.0.113.9"}
    reply = proxy.get("/api/lights", headers=headers)
    assert reply.status_code == 401 and reply.json()["error"] == "not_signed_in"
    assert refused_socket(proxy, f"ws://127.0.0.1:{PORT}/ws", headers=headers) == 4401


def test_a_listener_for_the_guarded_app_never_takes_the_peer_address_from_a_header():
    """SPEC-024: uvicorn's default would let X-Forwarded-For replace the 127.0.0.1 peer. Every listener is built by
    guarded_config, which cannot be asked to turn that back on."""
    assert guarded_config(object(), log_level="warning", proxy_headers=True).proxy_headers is False


def test_the_running_service_does_not_take_a_forwarded_for_header_as_the_peer_address(tmp_path):
    """SPEC-024, on the real service: uvicorn rewrites the peer address from X-Forwarded-For when the connection is
    from 127.0.0.1. A proxy on this Mac that sets no such header (`ssh -L`) would let a visitor pick the address the
    gate sees. The gate must see the real peer, loopback, and refuse."""
    folder = tmp_path / "bin"
    folder.mkdir()
    fake_tailscale(folder, RUNNING)
    service = subprocess.Popen(
        [sys.executable, "-I", "-B", "-m", "gaffer", "--demo", "--port", "0", "--session-from-stdin", "--data", str(tmp_path / "data")],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        env={"HOME": str(tmp_path), "PATH": f"{folder}:/usr/bin:/bin"}, start_new_session=True,
    )
    try:
        service.stdin.write(SECRET + "\n")
        service.stdin.flush()
        line = ""
        while "GAFFER_SERVICE_READY" not in line:
            assert service.poll() is None, "the service did not start"
            line = service.stdout.readline()
        base = f"http://127.0.0.1:{int(line.split('port=')[1])}"
        host = {"host": TAILNET_NAME}
        with httpx.Client(base_url=base, timeout=20) as web:
            web.cookies.set(COOKIE, SECRET)
            assert web.post("/api/phone", json={"enabled": True}).status_code == 200
            assert web.get("/api/phone?wait=1").json()["checking"] is False  # the Tailscale name is in
            web.cookies.clear()
            for forged in ({}, {"x-forwarded-for": TAILNET_IP}, {"x-forwarded-for": "fd7a:115c:a1e0::9"}):
                reply = web.get("/api/session", headers={**host, **forged})
                assert reply.status_code == 403 and reply.json()["error"] == "network_not_allowed", forged
    finally:
        if service.poll() is None:
            os.killpg(service.pid, signal.SIGKILL)
            service.wait()


def test_a_phone_with_the_pin_cannot_read_the_export_or_the_data_folder(studio):
    """The export holds the lights' keys and /api/health used to name a folder on the Mac."""
    pin = studio.switch_on()
    assert studio.sign_in(pin).status_code == 200
    refused = studio.phone.get("/api/export")
    assert refused.status_code == 403 and refused.json()["error"] == "mac_only"
    assert studio.mac.get("/api/export").status_code == 200
    for window in (studio.phone, studio.mac):
        health = window.get("/api/health")
        assert health.status_code == 200 and "data" not in health.json() and "/" not in health.text


async def test_a_tailscale_tool_that_never_answers_blocks_nothing(tmp_path):
    """Switching on, New PIN, switching off and the service stopping all go ahead while `tailscale` hangs,
    and the hung tool is killed. The 10 s only turns a hang into a failed test."""
    pids = tmp_path / "pids"
    script = tmp_path / "tailscale"
    script.write_text(f"#!/bin/sh\necho $$ >> {pids}\nexec sleep 120\n")  # 120 s: ends by itself if a test run dies
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    access = PhoneAccess(port=PORT, lan_ip=lambda: LAN, tailscale_cli=lambda: str(script))
    app = create_app(demo=True, data_dir=tmp_path / "data", phone=access)
    transport = httpx.ASGITransport(app=protect(app, SECRET, access), client=("127.0.0.1", 50000))
    async def tool_started(times: int) -> None:
        while not pids.exists() or len(pids.read_text().split()) < times:
            await asyncio.sleep(0.01)

    try:
        async with asyncio.timeout(10):
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(transport=transport, base_url=f"http://127.0.0.1:{PORT}", cookies={COOKIE: SECRET}) as mac:
                    on = (await mac.post("/api/phone", json={"enabled": True})).json()
                    assert on["enabled"] and on["checking"] and on["tailscale"] is None
                    assert [t["kind"] for t in on["targets"]] == ["wifi"]  # the Wi-Fi code does not wait for Tailscale
                    await tool_started(1)
                    assert (await mac.post("/api/phone/pin", json={})).status_code == 200  # answers while the tool hangs
                    assert (await mac.post("/api/phone", json={"enabled": False})).json()["enabled"] is False
                    assert (await mac.post("/api/phone", json={"enabled": True})).json()["enabled"] is True
                    await tool_started(2)
                # leaving the app switches phone access off: the service stops without waiting for the tool
        started = [int(p) for p in pids.read_text().split()]
        assert len(started) == 2
        for pid in started:
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)
    finally:
        for line in pids.read_text().split() if pids.exists() else []:
            try:
                os.kill(int(line), 9)
            except ProcessLookupError:
                pass


async def test_a_listener_that_fails_to_start_is_closed_and_the_mac_is_told_in_plain_words(tmp_path, monkeypatch):
    """uvicorn ends the program with SystemExit when it cannot start. The port must be free again for the next try."""
    import uvicorn

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    access = PhoneAccess(port=port, lan_ip=lambda: LAN, tailscale_cli=lambda: None)
    app = create_app(demo=True, data_dir=tmp_path / "data", phone=access)
    guarded = protect(app, SECRET, access)
    access.bind_listener(guarded, 1.0)
    transport = httpx.ASGITransport(app=guarded, client=("127.0.0.1", 50000))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url=f"http://127.0.0.1:{port}", cookies={COOKIE: SECRET}) as mac:
            real_startup = uvicorn.Server.startup

            async def cannot_start(self, sockets=None):
                raise SystemExit(1)

            monkeypatch.setattr(uvicorn.Server, "startup", cannot_start)
            failed = await mac.post("/api/phone", json={"enabled": True})
            assert failed.status_code == 503 and failed.json()["error"] == "phone_unavailable"
            assert "/" not in failed.json()["message"] and access.enabled is False
            monkeypatch.setattr(uvicorn.Server, "startup", real_startup)
            try:
                assert (await mac.post("/api/phone", json={"enabled": True})).status_code == 200  # the port was let go
            finally:
                await access.disable()


def switchable_tailscale(folder: Path) -> tuple[str, Path]:
    """A `tailscale` whose answer is whatever the file ``mode`` says: good, stopped, broken or hung."""
    (folder / "good.json").write_text(json.dumps(RUNNING))
    (folder / "stopped.json").write_text(json.dumps(STOPPED))
    mode = folder / "mode"
    mode.write_text("good")
    script = folder / "tailscale"
    script.write_text(
        f'#!/bin/sh\ncase "$(cat {mode})" in\n good) touch {folder}/answered; cat {folder}/good.json;;\n stopped) cat {folder}/stopped.json;;\n'
        f' broken) exit 1;;\n hung) touch {folder}/hung; exec sleep 120;;\nesac\n')  # 120 s: ends by itself if a test run dies
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return str(script), mode


def tailscale_state(studio: Studio) -> dict:
    """Ask the Mac for a new look and wait for it, as the panel does; and say whether a phone can use the tailnet name."""
    assert studio.mac.get("/api/phone").status_code == 200
    status = studio.mac.get("/api/phone?wait=1").json()
    status["name_accepted"] = studio.phone.get("/api/session", headers={"host": TAILNET_NAME}).status_code != 400
    return status


def test_a_failed_or_hung_tailscale_check_keeps_the_last_good_answer_and_a_stopped_tailscale_replaces_it(tmp_path):
    cli, mode = switchable_tailscale(tmp_path)
    with studio_with(tmp_path, cli) as s:
        pin = s.switch_on()
        assert s.sign_in(pin).status_code == 200
        assert tailscale_state(s)["name_accepted"] is True

        mode.write_text("broken")  # the tool fails (the Tailscale app is restarting)
        again = tailscale_state(s)
        assert again["tailscale"] is True and again["name_accepted"] is True
        assert s.phone.get("/api/lights", headers={"host": TAILNET_NAME}).status_code == 200  # the signed-in phone is still in

        mode.write_text("hung")  # the tool hangs; a new look ends the old one and the answer stays
        assert s.mac.get("/api/phone").status_code == 200
        assert s.phone.get("/api/session", headers={"host": TAILNET_NAME}).status_code == 200  # not "Invalid host header"

        mode.write_text("broken")  # switching off and on with a failing tool does not lose the names either
        s.mac.post("/api/phone", json={"enabled": False})
        s.mac.post("/api/phone", json={"enabled": True})
        assert tailscale_state(s)["name_accepted"] is True

        mode.write_text("stopped")  # the tool says Tailscale is not running: now the names go
        gone = tailscale_state(s)
        assert gone["tailscale"] is False and gone["name_accepted"] is False


def test_opening_the_panel_again_replaces_a_check_that_never_answered(tmp_path):
    cli, mode = switchable_tailscale(tmp_path)
    mode.write_text("hung")
    with studio_with(tmp_path, cli) as s:
        on = s.mac.post("/api/phone", json={"enabled": True}).json()
        assert on["checking"] is True and on["tailscale"] is None
        hung = tmp_path / "hung"
        while not hung.exists():  # the hung tool has started
            time.sleep(0.01)
        mode.write_text("good")  # Tailscale comes back; the next time the panel opens, the stuck check is replaced
        assert s.mac.get("/api/phone").status_code == 200
        answered = tmp_path / "answered"
        for _ in range(300):  # 3 s: only so that a check that is never replaced fails the test instead of hanging it
            if answered.exists():
                break
            time.sleep(0.01)
        assert answered.exists(), "the stuck check was not replaced"
        status = s.mac.get("/api/phone?wait=1").json()
        assert status["checking"] is False and status["tailscale"] is True
        assert [t["kind"] for t in status["targets"]] == ["wifi", "tailscale"]
