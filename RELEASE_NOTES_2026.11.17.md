# tado X v2026.11.17 — managed dashboard update reliability

Maintenance release for the automatically installed **tado X Heating**
sidebar panel introduced in v2026.11.16.

- Register the panel JavaScript URL with the exact version from
  `custom_components/tado/manifest.json`:
  `/tado/x-managed-panel.js?v=2026.11.17`. This prompts a fresh download
  of the managed panel module on HACS upgrades (after frontend reload).
- Explicitly declare Home Assistant's `frontend` and `http` component
  dependencies so the panel and static JS routes are ready at setup.
- Regression-test that the panel's URL derives from the integration version.

**No Lovelace dashboard YAML, JavaScript Resources registration, Home
Assistant helpers, or YAML automation changes are needed.** The previous
integration-managed panel and single optional Vaillant household-energy
feature stay unchanged. Existing user-created dashboards and automations
are not modified.

The packaged panel is available after HACS update and a Home Assistant
restart at `/tado-x-heating`. Reload the browser or Companion App frontend
if its cached copy is still displayed.

This release does not change tado heating actions, boiler temperatures,
schedules, gas statistics or existing boost recovery state.
