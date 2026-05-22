"""LTE / cellular WAN diagnostic sensors for Keenetic Router Pro.

These sensors hang off the per-WAN sub-device when the underlying
interface is identified as a cellular modem (UsbModem*, UsbQmi*,
UsbLte*). They surface the LTE-specific telemetry that the generic
WAN sensors don't expose: signal quality (RSSI, RSRP, RSRQ, SINR),
operator name, access technology (LTE / 5G / 3G), current band,
and registration / roaming state.

The Keenetic API delivers all of this inside the ``mobile`` sub-dict
of the raw ``show interface`` payload, so no additional API call is
needed — these sensors read straight from coordinator data that the
existing WAN fetch already produced.

Why expose them at all if HA's long-term statistics can derive
daily/monthly data totals from the existing RX/TX byte sensors?
Because signal quality is the single most useful piece of telemetry
for a router that's actually a cellular gateway: bad RSRP/SINR
explains slow speeds, an unexpected drop in registration explains
an outage, and the operator/band combo tells the user which tower
they're talking to. None of that is derivable from byte counters.
"""

from __future__ import annotations

from typing import Any, Optional

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
)

from ..coordinator import KeeneticCoordinator
from ..entity import WanEntity
from ..utils import safe_int


def is_lte_wan(wan: dict[str, Any] | None) -> bool:
    """Return True if a WAN dict represents a cellular / LTE modem.

    Identification is heuristic: Keenetic firmwares disagree on the
    capitalisation of interface types and on whether `mobile.*` data
    is exposed for newer modems. We accept the union of all forms
    seen in the wild rather than insist on a single canonical match.

    A future firmware that exposes a brand-new modem `type` will
    simply not get LTE sensors until added here — the generic WAN
    sensors (Public IP, RX/TX bytes, throughput, uptime) keep working
    regardless, so a misidentification just hides extra telemetry,
    it never breaks core functionality.
    """
    if not isinstance(wan, dict):
        return False
    iface_id = str(wan.get("id") or "").lower()
    iface_type = str(wan.get("type") or "").lower()
    if any(token in iface_id for token in ("usbmodem", "usbqmi", "usblte")):
        return True
    if iface_type in ("usblte", "usbmodem", "usbqmi", "usbmodemcdc"):
        return True
    if any(token in iface_type for token in ("mobile", "lte", "3g", "4g", "5g")):
        return True
    # Final fallback: a `mobile` sub-dict in raw is strong evidence
    # the firmware itself classified this as a cellular interface,
    # even if the type string doesn't match any of our known tokens.
    raw = wan.get("raw") if isinstance(wan, dict) else None
    if isinstance(raw, dict) and isinstance(raw.get("mobile"), dict):
        return True
    return False


class _LteSensorBase(WanEntity, SensorEntity):
    """Shared base for LTE-specific sensors hanging off a WAN sub-device.

    The mobile telemetry lives inside the WAN's ``raw.mobile`` dict.
    Centralising the lookup here keeps every child sensor reading
    from a single source of truth and ensures all of them go to
    ``unavailable`` together when the modem disconnects (rather than
    showing stale per-field values).
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

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
    def _mobile(self) -> dict[str, Any]:
        """Return the ``mobile`` sub-dict from this WAN's raw payload.

        Empty dict if the modem isn't reporting (transient disconnect,
        unsupported firmware field). Sensors then surface ``None`` as
        their native_value, which HA renders as "Unknown".
        """
        wan = self._wan
        if not wan:
            return {}
        raw = wan.get("raw")
        if not isinstance(raw, dict):
            return {}
        mobile = raw.get("mobile")
        return mobile if isinstance(mobile, dict) else {}

    @property
    def available(self) -> bool:
        # The sensor is "available" if we have *any* WAN data at all.
        # Whether the modem has registered with the network is then
        # the value the sensor reports, not its availability — that
        # way state history doesn't gap during transient drops.
        return self._wan is not None


# ---------------------------------------------------------------------------
# Text / identity sensors
# ---------------------------------------------------------------------------


class KeeneticLteOperatorSensor(_LteSensorBase):
    """Carrier / mobile network operator name (e.g. ``Vodafone TR``)."""
    _attr_icon = "mdi:cellphone-cog"

    @property
    def unique_id(self) -> str:
        return f"{self._entry_id}_wan_{self._wan_id}_lte_operator"

    @property
    def name(self) -> str:
        return "LTE Operator"

    @property
    def native_value(self) -> str | None:
        m = self._mobile
        return (
            m.get("operator")
            or m.get("provider")
            or m.get("plmn-description")
            or None
        )


class KeeneticLteTechnologySensor(_LteSensorBase):
    """Access technology currently in use (LTE / 5G / 3G / 2G)."""
    _attr_icon = "mdi:signal-cellular-3"

    @property
    def unique_id(self) -> str:
        return f"{self._entry_id}_wan_{self._wan_id}_lte_technology"

    @property
    def name(self) -> str:
        return "LTE Technology"

    @property
    def native_value(self) -> str | None:
        m = self._mobile
        # Firmwares use a few different field names — try them in
        # order of how informative they tend to be.
        return (
            m.get("access-technology")
            or m.get("technology")
            or m.get("mode")
            or m.get("network-type")
            or None
        )


class KeeneticLteBandSensor(_LteSensorBase):
    """Current LTE/5G band (e.g. ``B7``, ``B20``)."""
    _attr_icon = "mdi:radio-tower"

    @property
    def unique_id(self) -> str:
        return f"{self._entry_id}_wan_{self._wan_id}_lte_band"

    @property
    def name(self) -> str:
        return "LTE Band"

    @property
    def native_value(self) -> str | None:
        m = self._mobile
        band = m.get("band") or m.get("current-band") or m.get("active-band")
        return str(band) if band is not None else None


class KeeneticLteCellIdSensor(_LteSensorBase):
    """Serving cell ID. Useful for tracking which tower we're on."""
    _attr_icon = "mdi:cellphone-marker"
    _attr_entity_registry_enabled_default = False  # diagnostic, opt-in

    @property
    def unique_id(self) -> str:
        return f"{self._entry_id}_wan_{self._wan_id}_lte_cell_id"

    @property
    def name(self) -> str:
        return "LTE Cell ID"

    @property
    def native_value(self) -> str | None:
        m = self._mobile
        cell = m.get("cellid") or m.get("cell-id") or m.get("eci")
        return str(cell) if cell is not None else None


class KeeneticLteRegistrationSensor(_LteSensorBase):
    """Network-registration state (``home``, ``roaming``, ``searching``)."""
    _attr_icon = "mdi:cellphone-link"

    @property
    def unique_id(self) -> str:
        return f"{self._entry_id}_wan_{self._wan_id}_lte_registration"

    @property
    def name(self) -> str:
        return "LTE Registration"

    @property
    def native_value(self) -> str | None:
        m = self._mobile
        reg = (
            m.get("registration")
            or m.get("status")
            or m.get("network-status")
        )
        return str(reg) if reg is not None else None


# ---------------------------------------------------------------------------
# Signal-quality sensors
# ---------------------------------------------------------------------------


class KeeneticLteSignalSensor(_LteSensorBase):
    """Raw signal strength (RSSI). Negative dBm; closer to 0 is better."""
    _attr_icon = "mdi:signal"
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def unique_id(self) -> str:
        return f"{self._entry_id}_wan_{self._wan_id}_lte_signal"

    @property
    def name(self) -> str:
        return "LTE Signal"

    @property
    def native_value(self) -> int | None:
        m = self._mobile
        wan_raw = (self._wan or {}).get("raw") or {}
        # Try mobile.signal, mobile.rssi, then the top-level signal
        # field some firmwares put outside of mobile.*
        for key in ("signal", "rssi", "signal-strength"):
            v = m.get(key) if key in m else None
            if v is not None:
                return safe_int(v)
        v = wan_raw.get("signal")
        return safe_int(v) if v is not None else None


class KeeneticLteRsrpSensor(_LteSensorBase):
    """Reference Signal Received Power. -80 great, -100 ok, -120 bad."""
    _attr_icon = "mdi:signal-cellular-outline"
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def unique_id(self) -> str:
        return f"{self._entry_id}_wan_{self._wan_id}_lte_rsrp"

    @property
    def name(self) -> str:
        return "LTE RSRP"

    @property
    def native_value(self) -> int | None:
        v = self._mobile.get("rsrp")
        return safe_int(v) if v is not None else None


class KeeneticLteRsrqSensor(_LteSensorBase):
    """Reference Signal Received Quality. -10 great, -20 bad. Unit: dB.

    Note: not a SIGNAL_STRENGTH device_class because RSRQ is measured
    in dB (a ratio), not dBm (absolute power). HA's signal-strength
    icon set still applies via the explicit icon.
    """
    _attr_icon = "mdi:signal-cellular-2"
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def unique_id(self) -> str:
        return f"{self._entry_id}_wan_{self._wan_id}_lte_rsrq"

    @property
    def name(self) -> str:
        return "LTE RSRQ"

    @property
    def native_value(self) -> int | None:
        v = self._mobile.get("rsrq")
        return safe_int(v) if v is not None else None


class KeeneticLteSinrSensor(_LteSensorBase):
    """Signal-to-Interference-plus-Noise Ratio. >20 great, <5 bad. dB.

    Unit is dB (ratio). Same rationale as RSRQ: no SIGNAL_STRENGTH
    device_class, since that one is tied to dBm.
    """
    _attr_icon = "mdi:signal-cellular-1"
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def unique_id(self) -> str:
        return f"{self._entry_id}_wan_{self._wan_id}_lte_sinr"

    @property
    def name(self) -> str:
        return "LTE SINR"

    @property
    def native_value(self) -> int | None:
        v = self._mobile.get("sinr") or self._mobile.get("snr")
        return safe_int(v) if v is not None else None
