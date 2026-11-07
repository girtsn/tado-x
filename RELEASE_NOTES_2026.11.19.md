# tado X v2026.11.19 — API connectivity health

Stable HACS release.

- Add read-only diagnostic `binary_sensor.tado_x_api_cloud_connection_state` for main tado cloud polling, `binary_sensor.tado_x_settings_cloud_connection_state` for the separate DHW/flow settings API, and `sensor.tado_x_last_successful_update` for the most recent successful complete main poll. Actual entity IDs may differ if the registry already uses them.
- Connectivity indicators stay **available** when the source coordinator fails, rather than disappearing as `unavailable`; they report `on` for healthy data and `off` after failed polls.
- A local one-minute watchdog flags stale data even if polling stalls (15-minute main API threshold; 95-minute settings threshold). No additional tado cloud API requests.
- Present both cloud statuses and the last successful main update on the integration-managed Heating dashboard (Overview and Schedules) and standalone history card.
- Ship `examples/device_availability_dynamic_email.yaml` as a replacement for the user's existing Home Assistant availability automation. It monitors both cloud API entities independently, preserves five-minute outage confirmation and recovery emails, and retains Foscam / LG TV exclusions.

**Update:** Update through HACS and restart Home Assistant. Replace the existing automation **manually** with the supplied example in the Home Assistant automation editor. Do not create a duplicate automation. HACS cannot edit Home Assistant's existing automations.

**Limitation:** If HA starts while tado's main API is completely unreachable, the integration may never finish initial setup and cannot create its diagnostic entities; monitoring that scenario requires a separate HA-level startup watchdog. The diagnostics cannot detect an outage of Home Assistant itself.
