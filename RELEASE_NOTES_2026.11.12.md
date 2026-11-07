# tado X v2026.11.12 — whole-home heating controls and unified temperature chart

## Whole-home quick actions (new)

Adds one safe, explicit Home Assistant service for the **tado X Home screen
Quick Actions**, with one HOPS POST per action:

```yaml
action: tado.x_heating_quick_action
data:
  action: resume  # one of: off, resume, boost
```

- `off` — POST `quickActions/allOff`; all heating rooms enter OFF /
  frost protection until a manual change or Resume Schedules.
- `resume` — POST `quickActions/resumeSchedule`; cancel manual heating
  overrides and resume the heating Smart Schedules in all rooms.
- `boost` — POST `quickActions/boost`; all rooms request maximum setpoints
  for **30 minutes**, then automatically return to the Smart Schedules.

**This is heating only:** none of these commands directly changes domestic
hot water, the Vaillant boiler parameters, the configured tado maximum flow
temperature, or `autoAdaptation.enabled`. There is no documented basis to
claim a heating boost itself disables automatic flow adaptation, so the
integration does **not** change that switch as a side effect.

The new quick action buttons inside the **Heating Overview** custom card
require a browser confirmation and provide request feedback. HTTP acceptance
means only that tado received the command; real room states update with their
normal tado API polling. Commands are never run automatically or on start.

These APIs and results are derived from public tado X HOPS documentation and
third-party implementations, and have not yet been live-validated on this
specific boiler/bridge installation. Confirm the first commands in the tado app.

## One temperature graph, better control order

The existing `tado-x-settings-history-card.js` now places four tiles at the top:

1. Maximum configured heating flow
2. tado optimised (calculated) flow limit
3. **Automatic flow adaptation** — On/Off, with historical mean percentage
4. Outside temperature (auto-discovered from Home Assistant or specified)

DHW target and experimental DHW mode follow below, separate from heating.

One **combined, selectable multi-line Celsius graph** compares maximum flow,
optimised flow, DHW target and outside temperature. Tap the graph legend to
show or hide individual series. It retains the 24h, 7-day, 90-day, 1-year
and 3-year selections; empty periods are not invented or filled.

Outside temperature uses the pre-existing Home Assistant outdoor sensor where
possible, preferring tado's weather sensor. To choose your own physical
external weather sensor instead, set e.g.:

```yaml
type: custom:tado-x-settings-history-card
title: Heating flow and hot water
outdoor_entity: sensor.your_actual_external_temperature
```

The Outside source shown directly underneath the chart confirms which sensor
was selected. It will display a missing-source warning for an invalid manual
entity ID. No new API polling is added.

## Dashboard order

A full copy/paste dashboard is provided at
`examples/heating_dashboard.yaml`: **Overview → Consumption → Schedules**.
This changes only your dashboard configuration after you paste it through
Home Assistant's Raw configuration editor; a HACS update cannot rewrite a
user-created dashboard.

Register the existing resource with the version-busting URL:

`/tado/x-settings-history-card.js?v=2026.11.12`

`/tado/x-schedule-card.js?v=2026.11.12`
`/tado/x-heating-energy-card.js?v=2026.11.12`

The actual JS content of the latter two cards has not changed in this release.

## Historical consumption caveat

The early Vaillant backfill redistributed each day's measured gas total across
synthetic equal hourly buckets. The past hourly allocation therefore remains
a **provisional estimate** before 3 November 2026, not actual boiler burner
timing. The new dashboard labels this limitation. No historical Recorder
values have been changed by v2026.11.12.

### Testing

The backend unit test validates exactly one POST to each of the three paths
and verifies no flow-adaptation or domestic hot-water API calls occur.
Workflow additionally syntax-checks the custom Lovelace JavaScript cards.
