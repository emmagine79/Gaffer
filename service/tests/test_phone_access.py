"""Acceptance tests for phone access (SPEC-015), through the real HTTP and WebSocket interface.

The phone is a client whose peer address is not loopback (192.168.1.50, a Wi-Fi address). The Mac
window is a loopback client, signed in with the launch secret. Both reach the same app through the
same guard. Demo mode, so no Bluetooth is touched. Tailscale is a fake script that prints
`tailscale status --json` output; the real tool is never run.
"""

from __future__ import annotations

import json
import socket
import stat
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from websockets.asyncio.client import connect

from gaffer.app import create_app
from gaffer.phone import MAX_WRONG_GUESSES, PHONE_COOKIE, PIN_DIGITS, PhoneAccess
from gaffer.session import COOKIE, protect

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
    def __init__(self, phone: TestClient, mac: TestClient, access: PhoneAccess) -> None:
        self.phone, self.mac, self.access = phone, mac, access

    def switch_on(self) -> str:
        reply = self.mac.post("/api/phone", json={"enabled": True})
        assert reply.status_code == 200 and reply.json()["enabled"] is True
        return reply.json()["pin"]

    def sign_in(self, pin: str) -> httpx.Response:
        return self.phone.post("/api/session", json={"pin": pin})

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
        assert mac.get(f"/session?key={SECRET}", follow_redirects=False).status_code == 303
        assert mac.cookies.get(COOKIE) == SECRET
        yield Studio(phone, mac, access)


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
    assert studio.mac.get("/api/phone").json() == {"enabled": False, "pin": None, "locked": False, "tailscale": None, "targets": []}
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
    access.bind_listener(guarded, 1.0)
    name = {"host": TAILNET_NAME}  # a phone names the Tailscale name; here it reaches this machine over loopback
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as web:
            with pytest.raises(httpx.ConnectError):
                await web.get("/api/session", headers=name)
            await access.enable()
            try:
                assert (await web.get("/api/session", headers=name)).json()["error"] == "pin_required"
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
