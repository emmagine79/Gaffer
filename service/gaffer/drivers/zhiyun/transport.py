"""The Bluetooth side of the Zhiyun driver, behind a small interface so tests can use a fake.

``BleakTransport`` is the only code here that opens Bluetooth. Tests never create
one: they pass a transport that records bytes.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Protocol

from .protocol import NOTIFY_CHAR_UUID, SERVICE_UUID, WRITE_CHAR_UUID

# Timeouts from didim99/HA-Zhiyun-Light zhiyun_ble.py (_CONNECT_TIMEOUT, _WRITE_TIMEOUT).
CONNECT_TIMEOUT = 20.0
WRITE_TIMEOUT = 10.0


class LinkError(Exception):
    """The link failed. ``code`` is for the API; the message never carries a path."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class Link(Protocol):
    @property
    def connected(self) -> bool: ...

    async def write(self, data: bytes) -> None:
        """Write without response to the Zhiyun write characteristic."""

    async def close(self) -> None: ...


class Transport(Protocol):
    async def open(
        self, address: str, on_notify: Callable[[bytes], None], on_lost: Callable[[], None]
    ) -> Link: ...


class _BleakLink:
    def __init__(self, client, write_char) -> None:
        self._client = client
        self._char = write_char

    @property
    def connected(self) -> bool:
        return bool(self._client.is_connected)

    async def write(self, data: bytes) -> None:
        from bleak.exc import BleakError

        try:
            async with asyncio.timeout(WRITE_TIMEOUT):
                await self._client.write_gatt_char(self._char, data, response=False)
        except (TimeoutError, BleakError, OSError) as err:
            raise LinkError("write_failed", "The light did not accept the command.") from err

    async def close(self) -> None:
        try:
            async with asyncio.timeout(CONNECT_TIMEOUT):
                await self._client.disconnect()
        except Exception:  # noqa: BLE001 - bleak raises many types; the link is gone either way
            pass


_background: set[asyncio.Future[None]] = set()


def _release_in_background(client) -> None:
    closing = asyncio.ensure_future(_BleakLink(client, None).close())
    _background.add(closing)
    closing.add_done_callback(_background.discard)


async def _close_or_release(client) -> None:
    """Disconnect, bounded by CONNECT_TIMEOUT. A cancel during it hands the disconnect to the background."""
    try:
        await _BleakLink(client, None).close()
    except asyncio.CancelledError:
        _release_in_background(client)
        raise


class BleakTransport:
    """Connects with bleak to service 0xFEE9: write ``...9600``, notify ``...9601``."""

    async def open(self, address, on_notify, on_lost) -> Link:
        from bleak import BleakClient
        from bleak.exc import BleakError

        client = BleakClient(address, disconnected_callback=lambda _c: on_lost())
        try:
            async with asyncio.timeout(CONNECT_TIMEOUT):
                await client.connect()
            service = client.services.get_service(SERVICE_UUID)
            write_char = service.get_characteristic(WRITE_CHAR_UUID) if service else None
            notify_char = service.get_characteristic(NOTIFY_CHAR_UUID) if service else None
            if write_char is None or notify_char is None:
                raise LinkError("not_zhiyun", "The device does not offer the Zhiyun control service.")
            async with asyncio.timeout(WRITE_TIMEOUT):
                await client.start_notify(notify_char, lambda _c, data: on_notify(bytes(data)))
        except (TimeoutError, BleakError, OSError) as err:
            # A timed-out connect may still finish later: release the client so it cannot hold the light.
            await _close_or_release(client)
            raise LinkError("connect_failed", "Could not connect to the light.") from err
        except LinkError:
            await _close_or_release(client)
            raise
        except BaseException:
            # A cancel (shutdown) must not wait for the disconnect, which can take CONNECT_TIMEOUT.
            _release_in_background(client)
            raise
        return _BleakLink(client, write_char)
