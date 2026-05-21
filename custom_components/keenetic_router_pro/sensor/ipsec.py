"""IPsec VICI diagnostic sensors.

Surfaces a known strongSwan VICI failure mode visible in the router's
own log: ``IpSec::Vici::Stats: out of memory``. This indicates the
VICI socket has filled its buffer and IPsec status queries are
dropping — tunnels stay up but the integration's IPsec sensors stop
reflecting reality, which is otherwise invisible to the user. The
sensors here turn that log line into a dashboard signal.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory

from ..const import FAST_SCAN_INTERVAL
from ..coordinator import KeeneticCoordinator
from ..entity import ControllerEntity


# Display the configured polling cadence in the entity attributes so
# users can correlate counts with real-world rates ("3 OOMs in the
# last 5 minutes" vs "3 OOMs in the last week").
_IPSEC_DIAGNOSTIC_INTERVAL_SECONDS = FAST_SCAN_INTERVAL * 30


class KeeneticIpsecViciStatusSensor(ControllerEntity, SensorEntity):
    """Router-log-scraped IPsec VICI subsystem status.

    States:
      ok       -> no VICI OOM messages in the scanned log window
      warning  -> ≥1 VICI OOM message detected — IPsec status reads
                  may be silently dropping; user should restart the
                  IPsec service or reboot the router

    Polling cadence is intentionally slower than the main coordinator
    tick (~5 minutes) because each call runs `show log` on the router,
    which is moderately expensive on busy systems.
    """

    _attr_has_entity_name = True
    _attr_name = "IPsec VICI Status"
    _attr_icon = "mdi:shield-alert-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: KeeneticCoordinator, entry: ConfigEntry) -> None:
        ControllerEntity.__init__(self, coordinator, entry.entry_id, entry.title)

    @property
    def unique_id(self) -> str:
        return f"{self._entry_id}_ipsec_vici_status"

    @property
    def native_value(self) -> str | None:
        diagnostics = self.coordinator.data.get("ipsec_diagnostics") or {}
        return diagnostics.get("status")

    @property
    def icon(self) -> str:
        if self.native_value == "warning":
            return "mdi:shield-alert"
        if self.native_value == "ok":
            return "mdi:shield-check"
        return "mdi:shield-search"

    @property
    def available(self) -> bool:
        # Only render when the router exposes `show log` AND IPsec is
        # configured. Otherwise the sensor would sit as "unknown" on
        # firmwares without the IPsec component or log access, which
        # is dashboard noise.
        if not super().available:
            return False
        return bool(self.coordinator.data.get("ipsec_diagnostics"))

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        diagnostics = self.coordinator.data.get("ipsec_diagnostics") or {}
        if not diagnostics:
            return None
        return {
            "vici_out_of_memory_count": diagnostics.get("vici_out_of_memory_count"),
            "last_vici_out_of_memory": diagnostics.get("last_vici_out_of_memory"),
            "last_error_code": diagnostics.get("last_error_code"),
            "recent_matches": diagnostics.get("recent_matches"),
            "scanned_log_lines": diagnostics.get("scanned_log_lines"),
            "command": diagnostics.get("command"),
            "poll_interval_seconds": _IPSEC_DIAGNOSTIC_INTERVAL_SECONDS,
        }


class KeeneticIpsecViciOutOfMemorySensor(ControllerEntity, SensorEntity):
    """Count of IPsec VICI out-of-memory log entries in the scan window.

    MEASUREMENT (not TOTAL_INCREASING) because the count is a *window*
    over the recent log tail — when old log lines age out of the
    window, the count drops. Treating it as a monotonic total would
    make HA's recorder misinterpret the drop as a counter reset.
    """

    _attr_has_entity_name = True
    _attr_name = "IPsec VICI Out Of Memory"
    _attr_icon = "mdi:counter"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator: KeeneticCoordinator, entry: ConfigEntry) -> None:
        ControllerEntity.__init__(self, coordinator, entry.entry_id, entry.title)

    @property
    def unique_id(self) -> str:
        return f"{self._entry_id}_ipsec_vici_out_of_memory"

    @property
    def native_value(self) -> int | None:
        diagnostics = self.coordinator.data.get("ipsec_diagnostics") or {}
        value = diagnostics.get("vici_out_of_memory_count")
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
        return bool(self.coordinator.data.get("ipsec_diagnostics"))
