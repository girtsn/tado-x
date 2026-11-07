# tado X 2026.11.18

## Managed Heating dashboard

- Frontend module imports are versioned with the integration's manifest version, not just the panel entry module. The static routes also continue to disable HTTP caching.
- The dashboard uses one Energy-dashboard-style date selector at the top of the Overview tab. It offers **Today, Yesterday, This week, This month, This quarter, This year, Last 7 days, Last 30 days, Last 365 days, Last 12 months, Last 3 years**, and custom calendar ranges. The left/right buttons move to adjacent periods, and Now returns to the current one.
- The shared selected date range applies to the temperature/history and optional Vaillant gas-allocation cards. A selection is inclusive of the final calendar day; service calls carry an exclusive end timestamp.
- The gas-allocation history service supports optional `start_time` and `end_time` (offset-aware ISO 8601) while preserving its existing fixed-period API for standalone consumers. History is limited to a three-year range for requested exact bounds, uses locally stored Recorder statistics, and never alters source statistics.
- Standalone Lovelace cards keep their original period buttons.
- Sidebar icon: `mdi:gas-burner`.

## Updating

Update through HACS and restart Home Assistant. On normal page loading, the panel and child assets are fetched with the new integration version—no hard browser cache refresh should be necessary. If the open panel receives a new registered version, it reloads automatically. An already-open browser tab that receives no new panel metadata may still require an ordinary page reload.

Only the existing local Home Assistant Recorder history is available; a three-year range cannot show measurements recorded before the relevant sensors or allocation statistics were installed.
