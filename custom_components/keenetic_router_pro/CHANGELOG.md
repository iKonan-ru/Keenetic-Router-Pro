# Changelog — Keenetic Router Pro

## v1.8.0

This release rolls up eight rounds of work focused on security
hardening, data quality, performance, and a batch of long-standing
bug fixes against open GitHub issues. Existing entities, automations,
and dashboards continue to work — no breaking changes to entity_ids
or device identifiers.

### Fixed

- **#41 / #49 — Router system log spam.** Endpoints that don't exist
  on certain firmwares (e.g. `crypto/map` when IPsec is unconfigured,
  `WifiMaster0/AccessPoint1` on routers without Guest Wi-Fi) are now
  cached on the first 404 and never polled again. Reduces router-log
  errors from ~2,880/hour to ~2 total (one per missing endpoint per
  HA session).
- **#45 — Wrong Wi-Fi label on dual-band-with-different-SSID setups.**
  APs sharing a Keenetic bridge but broadcasting different SSIDs no
  longer collapse into a single logical network with an arbitrary
  label. A router exposing "Chapay" (2.4 GHz) and "Chapay_5G" (5 GHz)
  on the same bridge now produces two correctly-labelled sensors
  instead of one network mislabelled as "Wi-Fi Chapay_5G 2.4 GHz".
- **#45 — Missing QR for non-primary SSIDs.** Routers with three or
  more distinct SSIDs now get a dedicated `image.<router>_wifi_qr_ssid_<slug>`
  entity for each SSID not covered by the legacy main/guest entities.
  Simple setups (one main + one guest) still produce exactly two QR
  entities — no clutter.
- **#48 — Cross-subnet device tracker.** Devices on routed sub-LANs
  (e.g. 192.168.3.0/24 when HA sits in 192.168.1.0/24) that are
  reachable to the router but blocked from HA's ICMP probe can now
  be tracked correctly. New "Use router link state as fallback when
  ping fails" option, opt-in, surfaced at initial setup and in
  Options. Off by default — flat-LAN setups see no behaviour change.
- **#48 — Connected Devices count.** Cross-subnet hosts that report
  `active=false` but `link=up` (a Keenetic firmware quirk on routed
  sub-LANs) are now correctly counted as connected. Sensor previously
  under-reported by the number of cross-subnet devices.
- Apple/iOS trackers no longer cycle on/off when the entity emits
  no meaningful change in coordinator data (Sprint 3 fingerprint).
- Uptime sensors now use `TOTAL_INCREASING` state class so HA
  long-term statistics report sensible totals instead of derivatives.
  ⚠️ **Note:** automations that compared uptime to `0` to detect
  "router not yet started" need to be adjusted — uptime is now
  `None` (Unknown) in that case instead of `0`.

### Security

- All CLI arguments built into router commands are validated against
  a strict allow-list before being sent, defending against argument
  injection (Sprint 1).
- Passwords are now masked as dots in every config-flow form
  (initial setup, reauth, reconfigure).
- `KeeneticClient.__repr__` redacts username and password so
  exception tracebacks don't leak credentials to the logs.
- New `diagnostics.py` redacts host, MACs, IPs, SSIDs, PSKs, and
  per-client policy tables when the user downloads diagnostics.
- Credentials are now scrubbed from NDNS-related log messages.

### Added

- **Reauth flow.** Triggered automatically when the router rejects
  stored credentials (e.g. you changed the admin password). HA shows
  a Repair card; one click takes you to a username+password form
  that updates the entry in place — no entity history loss.
- **Reconfigure flow.** Manual entry from the integration card →
  Reconfigure. Lets you change host, port, SSL, challenge auth, or
  credentials on an existing entry. Entity history and automations
  are preserved.
- **DNS proxy diagnostic sensors** when the router exposes the
  `show/dns-proxy` endpoint: status + failed-requests counter, with
  DNS-over-HTTPS URIs redacted in the attribute payload.
- **IPsec VICI diagnostic sensors** when IPsec is configured:
  charon/strongswan health + an out-of-memory alarm sensor.
- Per-band Wi-Fi password / QR code support across all detected
  SSIDs (issue #45 path).

### Changed

- **HA's `runtime_data` is NOT used yet** — sticking with the
  `hass.data[DOMAIN][entry.entry_id]` pattern for now.
- Coordinator now publishes O(1) MAC / WAN / Mesh-node indexes in
  its `data` so child entities skip linear scans across 100+ clients.
- Auth flow is single-flighted with an `asyncio.Lock` — a 13-way
  parallel startup no longer launches 13 simultaneous auth attempts.
- Capability caches for `ping-check`, `ndns`, `crypto/map`,
  `dns-proxy`, and `ipsec-diagnostics` endpoints. After one 404 each
  endpoint is permanently skipped for the session.
- `async_get_client_stats` now treats `active=true OR link=up` as
  "connected" (previously mutually exclusive — see #48 above).

### Behind the scenes

- New `utils.py` with `safe_float`, `safe_int`, `clamp_percent`
  helpers that reject NaN/inf payloads — protects the recorder from
  ingesting bogus values that would otherwise blow up statistics.
- New `entity.py` `_FingerprintedCoordinatorEntity` mixin: child
  entities only write state when *their* slice of the coordinator
  payload has actually changed. Cuts state-write traffic by ~70%
  on busy routers.
- `SECURITY.md` ships with the integration documenting the threat
  model and the rationale behind plaintext-HTTP, the redaction set,
  and the CLI validator.

### Skipped (intentionally — kept upstream divergence small)

- `api/` package split — the codebase stays as a single `api.py`
  module by design.
- Mesh entity-ID migration — no collision risk in this codebase.
- KeenDNS Protected (remote-management) mode — see issue #43.
  Planned for a future release.

---

For maintainers: this version was assembled from eight code-review
sprints. Each individual sprint is preserved in the project's
internal records.
