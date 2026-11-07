# tado X v2026.11.16 — integration-managed Heating dashboard, no manual YAML updates

## New automatically installed Heating sidebar panel

The integration now registers **tado X Heating** directly in the Home
Assistant sidebar, at `/tado-x-heating`, using Home Assistant's documented
`panel_custom.async_register_panel()` mechanism.

The panel is bundled under `custom_components/tado/www/`, and automatically
loads the existing tado X controls and history card, schedule editor, and the
optional household Vaillant consumption card. No Lovelace dashboard
configuration, YAML copies, manual frontend Resources registrations or
independent JavaScript download are necessary.

- **Overview:** Heating Off, Resume Schedules, Eco Boost, Top Boost,
  current room schedule/override state, 30-minute recovery countdown,
  DHW target, adaptive flow control and long-term flow/outdoor graphs
- **Optional Vaillant consumption:** shown *only if* the per-entry household
  energy feature is enabled; otherwise not instantiated or queried
- **Schedules:** tado X weekly programme editor, as the last panel tab
- The bundled panel is served by the integration, so its UI arrives on the
  next HACS update + Home Assistant restart.

The new panel uses a distinct URL. **It does not overwrite, edit or delete
the existing user-created `Heating` dashboard.** Once the managed panel is
verified, users may hide the earlier dashboard from their sidebar.

## A single YAML template for those who prefer Lovelace

The fallback at `examples/heating_dashboard.yaml` is now universal:
it includes a complete Vaillant comparison section behind a standard
Home Assistant section `visibility` condition.

The read-only `binary_sensor.tado_x_vaillant_energy_enabled` reflects the
integration's existing *single* optional household feature checkbox. It is
**not** another setting or switch. The conditional section is shown when
that binary sensor is `on` and hidden otherwise. If the entity was renamed
in the local registry, update its entity ID in the YAML condition.

Because built-in Lovelace YAML cannot conditionally display whole dashboard
tabs, the optional Vaillant section is under Overview with Schedules last.
No additional Lovelace resources are needed for the new auto-managed panel.
The manually authored dashboard continues to require resource registration.

The redundant separate Vaillant-only YAML example has been removed.

## Automations and helpers

The existing **Eco/Top Boost expiry/recovery, retries and persisted mode**
already run as integration-native functions and storage. The corresponding
Home Assistant YAML automations, `input_datetime`, `input_text` or helper
entities are *not necessary* and are *not created* by this update.

The integration provides tado X sensors, switches, numbers, actions and
built-in history directly. It intentionally does **not** install or
overwrite user-written automations, helpers or configurations. Shipping
optional blueprints is possible for future flows, but should require
explicit user enablement so integration updates never silently modify
independent home automations.

## JavaScript coexistence

Guard existing card `customElements.define()` registrations to avoid errors
if a user still has the old Lovelace card Resources registered while the
managed panel imports the same card scripts.

## Installing and checking

1. Update HACS to `v2026.11.16`.
2. Restart Home Assistant.
3. Open sidebar **tado X Heating**, or navigate to `/tado-x-heating`.
4. Check current state, controls and Schedules.
5. If household Vaillant/myPyllant energy is configured, its consumption card
   should appear automatically under Overview.

No dashboard configuration or resource update required. Existing user-made
Heating dashboards stay untouched.

## Live validation status

GitHub's offline tests validate the frontend script syntax, service and
entity/source contracts, and the conditional YAML. The integration-managed
sidebar panel has not yet been exercised against the specific user's
Home Assistant frontend and should be verified after installing.
