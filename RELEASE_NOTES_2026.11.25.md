# tado X v2026.11.25 — effective presence and combined Home/Away history

## Separate manual control from observed occupancy

- Keep the existing Tado home `select.* Presence` entity with choices
  **Home / Away / Auto**. The selected mode reports whether geofencing is
  automatic or the household state is manually forced.
- Add a new **read-only Tado X Effective presence** sensor under the Tado
  home device. It reports the Tado cloud's observed `Home` / `Away`
  regardless of whether Auto or manual mode is selected. Unavailable
  cloud values remain unknown, not assumed Home.
- Both entities expose a non-secret `presence_scope` attribute and
  `tado_home_id` for reliable dashboard discovery. The selector also
  carries the current effective presence, and the sensor carries the
  selected control mode for inspection. Existing entity unique IDs
  and automation service behavior remain unchanged.

## Combined history in the managed Heating dashboard

- Add a **Home/Away control and presence history** card on Heating Overview
  using the dashboard's existing shared calendar.
- Compare three aligned, categorical timelines: Tado manual/Auto control,
  Tado observed Home/Away, and optional `sensor.home_presence` from
  Device Availability Digest.
- Show current values, timestamps, Home/Away/Auto/Unknown colors and a
  selectable list of recent state transitions. Current entity values open
  the normal HA More Info view.
- History comes from **Home Assistant Recorder**, using the built-in
  `history/history_during_period` WebSocket API with an initial state at
  the selected period boundary. No numeric averaging of occupancy, no
  implied data when records are missing, and no backfilling prior history.
- The chart is read-only: it does not set heating, change Tado presence,
  call the Tado cloud directly, or change external automations.

## Installation

Install through HACS, restart Home Assistant, and open **Heating → Overview**.
No dashboard YAML or resource registration is needed for the managed panel.
Ensure Recorder stores the new effective-presence sensor, the existing Tado
Presence select, and `sensor.home_presence` for the comparison to populate.
