"""LTE / cellular sensors for Keenetic Router Pro — issue #47.

Two distinct sensor families share this module:

1. **Data-usage sensors** (the primary issue #47 ask). Source: the
   ``show interface traffic-counter`` endpoint, which mirrors the
   "Data Usage & Limit" page in the Keenetic web UI. Five sensors
   per LTE interface plus two binary alarms: used / remaining /
   limit / threshold / days-until-reset / quota %, plus
   limit-exceeded and threshold-exceeded binary sensors.

2. **LTE diagnostics** (bonus telemetry). Source: the flat top-level
   fields on the LTE interface payload itself. Operator, technology,
   signal-level bars, RSSI / RSRP / RSRQ / CINR, band, roaming flag,
   modem temperature, connection state. These existed in an earlier
   sprint with the wrong field paths (assumed ``raw.mobile.*`` nesting
   that some firmwares use, but not the maintainer's UsbLte0 on
   Marvell-based hardware); this implementation reads the flat layout
   that real firmware actually returns.

Both families attach to the existing per-WAN sub-device that the
generic WAN sensors already populate — so a user with a 4G uplink
sees one device card with throughput, byte counters, signal quality
and quota usage all together, not two scattered devices.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    EntityCategory,
    SIGNAL_STRENGTH_DECIBELS,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    UnitOfInformation,
    UnitOfTemperature,
    UnitOfTime,
    PERCENTAGE,
)

from ..coordinator import KeeneticCoordinator
from ..entity import WanEntity
from ..utils import safe_float, safe_int

_LOGGER = logging.getLogger(__name__)


def is_lte_wan(wan: dict[str, Any] | None) -> bool:
    """Return True if a WAN dict represents a cellular / LTE modem.

    Uses the trait list as primary signal because Keenetic traits are
    stable across firmware versions. Falls back to type-name matching
    and id-prefix tokens for older firmwares that don't populate
    traits, and to the presence of a ``mobile.*`` sub-dict (used by
    nested-format firmware variants) as a last resort.
    """
    if not isinstance(wan, dict):
        return False
    raw = wan.get("raw") if isinstance(wan.get("raw"), dict) else {}
    iface_id = str(wan.get("id") or "").lower()
    iface_type = str(wan.get("type") or raw.get("type") or "").lower()
    traits = raw.get("traits") or wan.get("traits") or []
    if isinstance(traits, list) and (
        "UsbLte" in traits or "Mobile" in traits
    ):
        return True
    if iface_type in ("usblte", "usbmodem", "usbqmi", "usbmodemcdc"):
        return True
    if any(tok in iface_id for tok in ("usblte", "usbmodem", "usbqmi")):
        return True
    if any(tok in iface_type for tok in ("mobile", "lte", "3g", "4g", "5g")):
        return True
    # Some firmwares group mobile fields under raw.mobile.*; presence
    # of that sub-dict is a strong "is cellular" signal.
    if isinstance(raw.get("mobile"), dict):
        return True
    return False


# ---------------------------------------------------------------------------
# Shared base
# ---------------------------------------------------------------------------


class _LteSensorBase(WanEntity, SensorEntity):
    """Base for cellular sensors that read from coordinator data only.

    All LTE-family sensors are gated on the same "available" condition
    — if the coordinator doesn't have a WAN entry for our interface
    they all go to "unavailable" together, rather than each one
    independently rendering as 'Unknown'.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: KeeneticCoordinator,
        entry: ConfigEntry,
        wan_id: str,
    ) -> None:
        WanEntity.__init__(
            self, coordinator, entry.entry_id, entry.title, wan_id
        )

    @property
    def _raw(self) -> dict[str, Any]:
        """Flat top-level interface payload from ``show interface``."""
        wan = self._wan
        if not wan:
            return {}
        raw = wan.get("raw")
        return raw if isinstance(raw, dict) else {}

    @property
    def _mobile_sub(self) -> dict[str, Any]:
        """``raw.mobile.*`` sub-dict (for firmwares using nested layout).

        Several Keenetic firmware revisions place LTE telemetry under
        a ``mobile`` sub-key; others (e.g. UsbLte0 / Marvell-based
        modems verified by the maintainer) keep everything flat on
        the top-level interface payload. Sensors below check both
        layouts: flat first (more common on cellular-only modems),
        then the nested fallback.
        """
        m = self._raw.get("mobile")
        return m if isinstance(m, dict) else {}

    @property
    def _usage(self) -> dict[str, Any]:
        """Per-interface traffic-counter dict from the coordinator."""
        data = self.coordinator.data or {}
        usage_map = data.get("lte_data_usage") or {}
        return usage_map.get(self._wan_id, {}) if isinstance(usage_map, dict) else {}

    @property
    def available(self) -> bool:
        return self._wan is not None


# ---------------------------------------------------------------------------
# Data-usage sensors (issue #47 primary)
# ---------------------------------------------------------------------------


class _LteDataUsageSensorBase(_LteSensorBase):
    """Marker base: data-usage sensors are unavailable if traffic-counter is off.

    A user can disable the counter on the router without removing the
    SIM — that's a valid state, but in HA it should look "unavailable"
    rather than report 0 GB, so daily/monthly statistics don't accrue
    spurious zeros.
    """

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        usage = self._usage
        return bool(usage) and usage.get("enabled", False)


class KeeneticLteDataUsedSensor(_LteDataUsageSensorBase):
    """Current month-to-date data usage in GB."""
    _attr_icon = "mdi:download-network"
    _attr_native_unit_of_measurement = UnitOfInformation.GIGABYTES
    _attr_device_class = SensorDeviceClass.DATA_SIZE
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_suggested_display_precision = 2

    @property
    def unique_id(self) -> str:
        return f"{self._entry_id}_wan_{self._wan_id}_lte_data_used"

    @property
    def name(self) -> str:
        return "Data Used"

    @property
    def native_value(self) -> float | None:
        return self._usage.get("used_gb")


class KeeneticLteDataRemainingSensor(_LteDataUsageSensorBase):
    """Remaining data in GB until the monthly quota is reached."""
    _attr_icon = "mdi:gauge"
    _attr_native_unit_of_measurement = UnitOfInformation.GIGABYTES
    _attr_device_class = SensorDeviceClass.DATA_SIZE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2

    @property
    def unique_id(self) -> str:
        return f"{self._entry_id}_wan_{self._wan_id}_lte_data_remaining"

    @property
    def name(self) -> str:
        return "Data Remaining"

    @property
    def native_value(self) -> float | None:
        return self._usage.get("remaining_gb")


class KeeneticLteDataLimitSensor(_LteDataUsageSensorBase):
    """Configured monthly data limit in GB (diagnostic)."""
    _attr_icon = "mdi:database-arrow-up"
    _attr_native_unit_of_measurement = UnitOfInformation.GIGABYTES
    _attr_device_class = SensorDeviceClass.DATA_SIZE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_suggested_display_precision = 2

    @property
    def unique_id(self) -> str:
        return f"{self._entry_id}_wan_{self._wan_id}_lte_data_limit"

    @property
    def name(self) -> str:
        return "Data Limit"

    @property
    def native_value(self) -> float | None:
        return self._usage.get("limit_gb")


class KeeneticLteDataThresholdSensor(_LteDataUsageSensorBase):
    """Warning threshold in GB (diagnostic)."""
    _attr_icon = "mdi:alert-circle-outline"
    _attr_native_unit_of_measurement = UnitOfInformation.GIGABYTES
    _attr_device_class = SensorDeviceClass.DATA_SIZE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_suggested_display_precision = 2

    @property
    def unique_id(self) -> str:
        return f"{self._entry_id}_wan_{self._wan_id}_lte_data_threshold"

    @property
    def name(self) -> str:
        return "Data Threshold"

    @property
    def native_value(self) -> float | None:
        return self._usage.get("threshold_gb")


class KeeneticLteDaysUntilResetSensor(_LteDataUsageSensorBase):
    """Days remaining until the monthly counter resets."""
    _attr_icon = "mdi:calendar-clock"
    _attr_native_unit_of_measurement = UnitOfTime.DAYS
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def unique_id(self) -> str:
        return f"{self._entry_id}_wan_{self._wan_id}_lte_days_until_reset"

    @property
    def name(self) -> str:
        return "Days Until Reset"

    @property
    def native_value(self) -> int | None:
        return self._usage.get("days_left")


class KeeneticLteQuotaUsageSensor(_LteDataUsageSensorBase):
    """Current quota usage as a percentage of the configured limit.

    Computed locally rather than from the router because the router's
    "threshold" value is itself a percentage of the limit (e.g. 90 %)
    — the router never reports "current % of limit", just the absolute
    value-in-GB pair. Local computation also means the percentage
    updates the moment ``used_gb`` ticks, even between coordinator
    refreshes that miss a counter-save event.
    """
    _attr_icon = "mdi:percent"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1

    @property
    def unique_id(self) -> str:
        return f"{self._entry_id}_wan_{self._wan_id}_lte_quota_usage"

    @property
    def name(self) -> str:
        return "Quota Usage"

    @property
    def native_value(self) -> float | None:
        usage = self._usage
        used = usage.get("used_gb")
        limit = usage.get("limit_gb")
        if used is None or limit is None or limit <= 0:
            return None
        pct = (used / limit) * 100.0
        # Defensive clamp: routers occasionally over-report by a sliver
        # past 100 % between threshold-trigger and counter-reset, but
        # values like 250 % would just look broken.
        return max(0.0, min(pct, 999.0))


# ---------------------------------------------------------------------------
# LTE telemetry sensors (bonus diagnostics)
# ---------------------------------------------------------------------------


def _flat_or_nested(raw: dict[str, Any], mobile: dict[str, Any], *keys: str) -> Any:
    """Find a value by trying it at the flat root first, then under mobile.*.

    Both layouts are seen in the wild; we want every sensor to work on
    both without each one duplicating the fallback chain inline.
    """
    for k in keys:
        if k in raw and raw[k] not in (None, ""):
            return raw[k]
    for k in keys:
        if k in mobile and mobile[k] not in (None, ""):
            return mobile[k]
    return None


class KeeneticLteOperatorSensor(_LteSensorBase):
    """Mobile network operator name (e.g. ``Avea``)."""
    _attr_icon = "mdi:cellphone-cog"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def unique_id(self) -> str:
        return f"{self._entry_id}_wan_{self._wan_id}_lte_operator"

    @property
    def name(self) -> str:
        return "LTE Operator"

    @property
    def native_value(self) -> str | None:
        v = _flat_or_nested(
            self._raw, self._mobile_sub,
            "operator", "provider", "plmn-description",
        )
        return str(v) if v is not None else None


class KeeneticLteTechnologySensor(_LteSensorBase):
    """Access technology in use (``4G`` / ``5G`` / ``3G`` / ``2G``).

    On firmwares using the flat layout the ``mobile`` key on the
    interface payload is *itself* a string with the technology name
    (verified against UsbLte0 returning ``mobile: "4G"``). On nested
    layouts the equivalent value lives at ``mobile.access-technology``.
    We accept both.
    """
    _attr_icon = "mdi:signal-cellular-3"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def unique_id(self) -> str:
        return f"{self._entry_id}_wan_{self._wan_id}_lte_technology"

    @property
    def name(self) -> str:
        return "LTE Technology"

    @property
    def native_value(self) -> str | None:
        # Flat: raw.mobile is a string ("4G"). Nested: raw.mobile is a
        # dict, so check nested keys instead.
        flat_mobile = self._raw.get("mobile")
        if isinstance(flat_mobile, str) and flat_mobile.strip():
            return flat_mobile
        v = _flat_or_nested(
            self._raw, self._mobile_sub,
            "access-technology", "technology", "mode", "network-type",
        )
        return str(v) if v is not None else None


class KeeneticLteSignalLevelSensor(_LteSensorBase):
    """Signal bars (0-5). Driven by the modem's own bucketing."""
    _attr_icon = "mdi:signal"
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def unique_id(self) -> str:
        return f"{self._entry_id}_wan_{self._wan_id}_lte_signal_level"

    @property
    def name(self) -> str:
        return "LTE Signal Level"

    @property
    def native_value(self) -> int | None:
        v = _flat_or_nested(self._raw, self._mobile_sub, "signal-level")
        return safe_int(v)


class KeeneticLteRssiSensor(_LteSensorBase):
    """Raw signal strength (RSSI). Negative dBm; closer to 0 is better."""
    _attr_icon = "mdi:wifi-strength-2"
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def unique_id(self) -> str:
        return f"{self._entry_id}_wan_{self._wan_id}_lte_rssi"

    @property
    def name(self) -> str:
        return "LTE RSSI"

    @property
    def native_value(self) -> int | None:
        v = _flat_or_nested(self._raw, self._mobile_sub, "rssi", "signal")
        return safe_int(v)


class KeeneticLteRsrpSensor(_LteSensorBase):
    """Reference Signal Received Power. -80 great, -110 poor."""
    _attr_icon = "mdi:signal-cellular-outline"
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def unique_id(self) -> str:
        return f"{self._entry_id}_wan_{self._wan_id}_lte_rsrp"

    @property
    def name(self) -> str:
        return "LTE RSRP"

    @property
    def native_value(self) -> int | None:
        v = _flat_or_nested(self._raw, self._mobile_sub, "rsrp")
        return safe_int(v)


class KeeneticLteRsrqSensor(_LteSensorBase):
    """Reference Signal Received Quality (dB ratio).

    No SIGNAL_STRENGTH device_class because RSRQ is a ratio in dB,
    not absolute power in dBm.
    """
    _attr_icon = "mdi:signal-cellular-2"
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def unique_id(self) -> str:
        return f"{self._entry_id}_wan_{self._wan_id}_lte_rsrq"

    @property
    def name(self) -> str:
        return "LTE RSRQ"

    @property
    def native_value(self) -> int | None:
        v = _flat_or_nested(self._raw, self._mobile_sub, "rsrq")
        return safe_int(v)


class KeeneticLteCinrSensor(_LteSensorBase):
    """Carrier-to-Interference-plus-Noise Ratio (dB).

    Some firmwares expose this as ``sinr`` (the more common acronym);
    Marvell-based Keenetic LTE modems report it as ``cinr``. We accept
    either field name.
    """
    _attr_icon = "mdi:signal-cellular-1"
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def unique_id(self) -> str:
        return f"{self._entry_id}_wan_{self._wan_id}_lte_cinr"

    @property
    def name(self) -> str:
        return "LTE CINR"

    @property
    def native_value(self) -> int | None:
        v = _flat_or_nested(self._raw, self._mobile_sub, "cinr", "sinr", "snr")
        return safe_int(v)


class KeeneticLteBandSensor(_LteSensorBase):
    """Current LTE/5G band (e.g. ``1``, ``B7``)."""
    _attr_icon = "mdi:radio-tower"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def unique_id(self) -> str:
        return f"{self._entry_id}_wan_{self._wan_id}_lte_band"

    @property
    def name(self) -> str:
        return "LTE Band"

    @property
    def native_value(self) -> str | None:
        v = _flat_or_nested(
            self._raw, self._mobile_sub,
            "band", "current-band", "active-band",
        )
        return str(v) if v is not None else None


class KeeneticLteRoamingSensor(_LteSensorBase):
    """Whether the SIM is currently roaming (text yes/no for visibility)."""
    _attr_icon = "mdi:airplane"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def unique_id(self) -> str:
        return f"{self._entry_id}_wan_{self._wan_id}_lte_roaming"

    @property
    def name(self) -> str:
        return "LTE Roaming"

    @property
    def native_value(self) -> str | None:
        v = _flat_or_nested(self._raw, self._mobile_sub, "roaming")
        if v is None:
            return None
        # Surface as text rather than bool — HA renders the latter as
        # On/Off via switches, but this is a sensor (read-only fact).
        return "yes" if bool(v) else "no"


class KeeneticLteTemperatureSensor(_LteSensorBase):
    """Modem temperature in Celsius (diagnostic)."""
    _attr_icon = "mdi:thermometer"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def unique_id(self) -> str:
        return f"{self._entry_id}_wan_{self._wan_id}_lte_temperature"

    @property
    def name(self) -> str:
        return "LTE Modem Temperature"

    @property
    def native_value(self) -> float | None:
        v = _flat_or_nested(self._raw, self._mobile_sub, "temperature")
        return safe_float(v)


class KeeneticLteConnectionStateSensor(_LteSensorBase):
    """Modem connection state (e.g. ``Connected``, ``Registered``)."""
    _attr_icon = "mdi:cellphone-link"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def unique_id(self) -> str:
        return f"{self._entry_id}_wan_{self._wan_id}_lte_connection_state"

    @property
    def name(self) -> str:
        return "LTE Connection State"

    @property
    def native_value(self) -> str | None:
        v = _flat_or_nested(
            self._raw, self._mobile_sub,
            "connection-state", "registration", "status", "network-status",
        )
        return str(v) if v is not None else None


class KeeneticLteApnSensor(_LteSensorBase):
    """Configured APN (e.g. ``internet``)."""
    _attr_icon = "mdi:earth"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False  # niche, opt-in

    @property
    def unique_id(self) -> str:
        return f"{self._entry_id}_wan_{self._wan_id}_lte_apn"

    @property
    def name(self) -> str:
        return "LTE APN"

    @property
    def native_value(self) -> str | None:
        v = _flat_or_nested(self._raw, self._mobile_sub, "apn")
        if isinstance(v, dict):
            v = v.get("apn") or v.get("name")
        return str(v) if v else None
