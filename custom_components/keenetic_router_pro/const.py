"""Constants for the Keenetic Router Pro integration."""

DOMAIN = "keenetic_router_pro"
DEFAULT_PORT = 100
DEFAULT_SSL = False
FAST_SCAN_INTERVAL = 10
SLOW_SCAN_INTERVAL = 60
PING_SCAN_INTERVAL = 3  # legacy default, kept for backwards compatibility
DEFAULT_PING_INTERVAL = 5
MIN_PING_INTERVAL = 5
MAX_PING_INTERVAL = 300
CONF_PING_INTERVAL = "ping_interval"
DATA_CLIENT = "client"
DATA_COORDINATOR = "coordinator"
DATA_PING_COORDINATOR = "ping_coordinator"
CONF_TRACKED_CLIENTS = "tracked_clients"
CONF_USE_CHALLENGE_AUTH = "use_challenge_auth"
EVENT_NEW_DEVICE = f"{DOMAIN}_new_device"
COORD_RC_INTERFACE = "coord_rc_interface"

# Sprint 7 / issue #48: device-tracker fallback to router-reported link
# state when ICMP ping fails. Catches the cross-subnet scenario where
# tracked devices are reachable to the router (link=up) but unreachable
# to HA's ICMP probe due to firewall rules or routed sub-LANs. Default
# OFF so the feature is strictly opt-in — most home users sit on a flat
# LAN where ICMP is reliable and the router-state fallback would only
# introduce small false-positive windows during disconnect (router takes
# a few seconds to flip link=down on real disconnects). Users who
# actually have cross-subnet devices can enable this in the initial
# setup form OR later via Options.
CONF_LINK_STATE_FALLBACK = "link_state_fallback"
DEFAULT_LINK_STATE_FALLBACK = False
