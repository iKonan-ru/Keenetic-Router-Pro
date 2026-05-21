"""DNS proxy / DoH upstream diagnostic sensors.

Surfaces the health of the router's DNS proxy + DNS-over-HTTPS
upstream chain as Home Assistant sensors. Useful for catching the
failure mode where the router still has raw IP connectivity but DoH
upstreams have stopped answering — clients lose name resolution while
ping/HTTP-to-IP keeps working, which is otherwise hard to spot.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory

from ..coordinator import KeeneticCoordinator
from ..entity import ControllerEntity


class KeeneticDnsProxyStatusSensor(ControllerEntity, SensorEntity):
    """Overall DNS proxy health (ok / degraded / down / unknown).

    Status semantics (computed in api.py async_get_dns_proxy_status):
      ok         -> ≥1 upstream and (DoH active OR ≥1 active DNS)
      degraded   -> ≥1 upstream configured but nothing answering
      down       -> 0 upstreams configured
      unknown    -> endpoint not supported / payload couldn't be parsed
    """

    _attr_has_entity_name = True
    _attr_name = "DNS Proxy Status"
    _attr_icon = "mdi:dns"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: KeeneticCoordinator, entry: ConfigEntry) -> None:
        ControllerEntity.__init__(self, coordinator, entry.entry_id, entry.title)

    @property
    def unique_id(self) -> str:
        return f"{self._entry_id}_dns_proxy_status"

    @property
    def native_value(self) -> str | None:
        dns_proxy = self.coordinator.data.get("dns_proxy") or {}
        return dns_proxy.get("status")

    @property
    def icon(self) -> str:
        status = self.native_value
        if status == "ok":
            return "mdi:dns"
        if status in ("degraded", "down"):
            return "mdi:dns-outline"
        return "mdi:help-network"

    @property
    def available(self) -> bool:
        # Only report available when the router actually exposes the
        # DNS proxy endpoint. Otherwise the sensor would surface as
        # "unknown" forever on firmwares without DoH support, which
        # adds noise to dashboards.
        if not super().available:
            return False
        return bool(self.coordinator.data.get("dns_proxy"))

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        dns_proxy = self.coordinator.data.get("dns_proxy") or {}
        if not dns_proxy:
            return None
        # The `proxies` list contains DoH URIs that have already been
        # run through the path-stripping redactor in api.py — the
        # account-id portion of NextDNS-style URIs never reaches here.
        return {
            "client_path_uses_doh": dns_proxy.get("client_path_uses_doh"),
            "proxy_count": dns_proxy.get("proxy_count"),
            "doh_server_count": dns_proxy.get("doh_server_count"),
            "dns_server_count": dns_proxy.get("dns_server_count"),
            "active_dns_server_count": dns_proxy.get("active_dns_server_count"),
            "requests_sent": dns_proxy.get("requests_sent"),
            "failed_requests": dns_proxy.get("failed_requests"),
            "proxies": dns_proxy.get("proxies"),
        }


class KeeneticDnsProxyFailedRequestsSensor(ControllerEntity, SensorEntity):
    """Cumulative failed DNS proxy upstream requests from router stats.

    HA recorder stores this as MEASUREMENT (not TOTAL_INCREASING)
    because Keenetic resets the counter on a router reboot but ALSO
    sometimes resets it mid-session when the DNS proxy module
    reloads. A monotonic counter would interpret each reset as a
    rollover and graph it incorrectly. MEASUREMENT lets the user see
    spikes without that artifact.
    """

    _attr_has_entity_name = True
    _attr_name = "DNS Proxy Failed Requests"
    _attr_icon = "mdi:alert-circle-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator: KeeneticCoordinator, entry: ConfigEntry) -> None:
        ControllerEntity.__init__(self, coordinator, entry.entry_id, entry.title)

    @property
    def unique_id(self) -> str:
        return f"{self._entry_id}_dns_proxy_failed_requests"

    @property
    def native_value(self) -> int | None:
        dns_proxy = self.coordinator.data.get("dns_proxy") or {}
        value = dns_proxy.get("failed_requests")
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        return bool(self.coordinator.data.get("dns_proxy"))
