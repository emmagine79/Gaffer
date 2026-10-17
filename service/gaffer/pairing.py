"""Adding a factory-fresh light to our mesh: provision it, then bind its app key.

Two connections, the same two steps the vendor app and the ``godox-mesh`` CLI
take:

1. **Provision** over the Mesh Provisioning Service: an ECDH exchange gives the
   light our network key and its unicast address, and gives us its device key.
2. **Bind** over the Mesh Proxy Service, now that the light is on the network:
   Config AppKey Add and Model App Bind, encrypted with the device key, so the
   light accepts commands sealed with our application key.

Between the two the light tears down its provisioning service and brings up
the proxy, so the second connection must not reuse a cached GATT table, and it
can take a moment to come back; the bind is retried.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from collections.abc import Callable
from typing import Any, Protocol

from godox_mesh_bt.config_session import ConfigSession
from godox_mesh_bt.provisioning import ProvisioningSession

from .link import SequenceVault

logger = logging.getLogger(__name__)

BIND_ATTEMPTS = 4
BIND_RETRY_DELAY = 1.5

Step = Callable[[str], None]


@dataclasses.dataclass(frozen=True, slots=True)
class Paired:
    device_key: str
    num_elements: int


class Pairer(Protocol):
    async def __call__(self, target: Any, *, address: str, vault: SequenceVault, node_address: int,
                       on_step: Step) -> Paired: ...


def _client_factory(target: Any) -> Callable[[str], Any]:
    from bleak import BleakClient

    def factory(_address: str) -> Any:
        # The light's services change as it joins the mesh: never trust a cached table.
        return BleakClient(target, timeout=20.0, winrt={"use_cached_services": False})

    return factory


async def pair_light(
    target: Any,
    *,
    address: str,
    vault: SequenceVault,
    node_address: int,
    on_step: Step,
    provision: type[ProvisioningSession] = ProvisioningSession,
    bind: type[ConfigSession] = ConfigSession,
    client_factory: Callable[[Any], Callable[[str], Any]] = _client_factory,
    retry_delay: float = BIND_RETRY_DELAY,
) -> Paired:
    """Provision ``target`` onto the vault's network at ``node_address`` and bind it."""
    state = vault.fresh_session()
    factory = client_factory(target)

    on_step("provisioning")
    provisioned = await provision(
        address=address,
        net_key=bytes.fromhex(state.network_key),
        key_index=0,
        iv_index=state.iv_index,
        unicast_address=node_address,
        provisioner_address=state.provisioner_address,
        client_factory=factory,
    ).run()

    on_step("binding")
    bind_state = dataclasses.replace(
        vault.fresh_session(), device_key=provisioned.device_key, node_address=node_address,
    )
    last_error: Exception | None = None
    for attempt in range(1, BIND_ATTEMPTS + 1):
        try:
            final = await bind(address=address, state=bind_state, client_factory=factory).run()
        except Exception as err:  # noqa: BLE001 - the light is still restarting its services
            last_error = err
            logger.info("bind attempt %d failed: %s", attempt, err)
            await asyncio.sleep(retry_delay)
            # Each attempt may have spent sequence numbers before failing.
            bind_state = dataclasses.replace(vault.fresh_session(), device_key=provisioned.device_key,
                                             node_address=node_address)
            continue
        vault.write(dataclasses.replace(final, device_key="", node_address=0))
        on_step("bound")
        return Paired(device_key=provisioned.device_key, num_elements=max(1, provisioned.num_elements))
    raise RuntimeError(
        f"the light joined the network but would not take its key ({last_error}). "
        "Factory-reset it and pair again."
    )
