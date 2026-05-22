"""Number entities for Keenetic Router Pro.

Per-client bandwidth-limit slider (issue #42). Each tracked client
gets a single ``number`` entity that mirrors the ``ip traffic-shape
host <mac> rate <kbit/s>`` configuration on the router. Setting the
slider to a positive value applies the limit; setting it to 0 removes
the limit entirely.

The Keenetic CLI treats traffic-shape as a single combined rate, not
a separate download/upload pair — so we expose one number per client,
not two. The unit is kbit/s (the router's native unit). Users who
think in Mbps can type 10000 for 10 Mbps; HA's number UI accepts
direct entry in BOX mode.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.number import (
    NumberEntity,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfDataRate
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import KeeneticClient
from .const import DOMAIN, DATA_CLIENT, DATA_COORDINATOR, CONF_TRACKED_CLIENTS
from .coordinator import KeeneticCoordinator
from .entity import ClientEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up bandwidth-limit number entities for tracked clients."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: KeeneticCoordinator = data[DATA_COORDINATOR]
    client: KeeneticClient = data[DATA_CLIENT]
    entities: list[NumberEntity] = []

    tracked_clients = entry.data.get(CONF_TRACKED_CLIENTS, [])

    for client_info in tracked_clients:
        if not isinstance(client_info, dict):
            continue
        mac = str(client_info.get("mac") or "").lower()
        if not mac:
            continue
        name = client_info.get("name") or mac.upper()
        initial_ip = client_info.get("ip")
        entities.append(
            KeeneticClientBandwidthLimitNumber(
                coordinator=coordinator,
                entry=entry,
                api_client=client,
                mac=mac,
                label=name,
                initial_ip=initial_ip,
            )
        )

    if entities:
        async_add_entities(entities)


class KeeneticClientBandwidthLimitNumber(ClientEntity, NumberEntity):
    """Slider for per-client bandwidth limit (combined down + up).

    Setting value=0 removes the limit on the router; any positive
    value (in kbit/s) applies it and persists the running config.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:speedometer"
    _attr_native_unit_of_measurement = UnitOfDataRate.KILOBITS_PER_SECOND
    _attr_native_min_value = 0
    # 100 Mbit/s default ceiling. Routers that actually shape >100 Mbit/s
    # are rare on residential lines; users on faster connections can
    # type any value into the BOX-mode number — the entity still
    # accepts it because async_set_native_value clamps server-side
    # rather than client-side.
    _attr_native_max_value = 100000
    _attr_native_step = 100
    _attr_mode = NumberMode.BOX

    # The bandwidth-limit number reads from coordinator data
    # (``traffic_shapes`` dict) rather than the client row, so the
    # client-row fingerprint dedup doesn't apply here — we want a
    # state write whenever the router's view of the rate changes
    # (e.g. someone edited it in the Keenetic web UI in parallel).
    _FINGERPRINT_IGNORE: frozenset = frozenset()

    def __init__(
        self,
        coordinator: KeeneticCoordinator,
        entry: ConfigEntry,
        api_client: KeeneticClient,
        mac: str,
        label: str,
        initial_ip: str | None,
    ) -> None:
        ClientEntity.__init__(
            self,
            coordinator=coordinator,
            entry_id=entry.entry_id,
            title=entry.title,
            mac=mac,
            label=label,
            initial_ip=initial_ip,
        )
        self._api_client = api_client

    @property
    def unique_id(self) -> str:
        return f"{self._entry_id}_client_{self._mac}_bandwidth_limit"

    @property
    def name(self) -> str:
        return "Bandwidth Limit"

    @property
    def native_value(self) -> float | None:
        """Current rate from the router (kbit/s), or 0 if unlimited.

        A return of 0 means there's no traffic-shape line for this MAC
        in the router's running config — i.e. the client has no
        bandwidth restriction. The slider visually rests at the
        minimum in that case.
        """
        data = self.coordinator.data or {}
        shapes = data.get("traffic_shapes") or {}
        # Normalise the key the same way the API method does so a
        # mixed-case stored MAC still finds its rate.
        key = self._mac.lower().replace("-", ":")
        rate = shapes.get(key)
        if isinstance(rate, int) and rate > 0:
            return float(rate)
        return 0.0

    async def async_set_native_value(self, value: float) -> None:
        """Apply (or clear) the bandwidth limit on the router.

        Routes ``value > 0`` to ``ip traffic-shape host <mac> rate
        <kbit/s>`` and ``value == 0`` to the corresponding ``no``
        command. Both paths persist the running config via
        ``system configuration save`` inside the API method. We then
        request a coordinator refresh so the slider reflects the new
        state on the next tick — important for the user to see the
        change actually landed, not just that the request succeeded.
        """
        try:
            await self._api_client.async_set_client_bandwidth(
                self._mac, int(value)
            )
        except Exception:  # noqa: BLE001
            _LOGGER.exception(
                "Failed to set bandwidth limit for client %s to %s kbit/s",
                self._mac, value,
            )
            raise
        await self.coordinator.async_request_refresh()
