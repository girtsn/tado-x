# tado X integration — Home Assistant fork

## New in 2026.11.8 — permanent settings history

The existing editable `number` and `switch` entities are not sufficient to
guarantee long-term statistics beyond the Recorder state-retention window.
This release adds four independent **read-only sensor** histories for:

- `DHW target temperature history` (°C)
- `Maximum flow temperature history` (°C)
- `Optimised heating flow limit` (°C; already present in v2026.11.7)
- `Flow adaptation enabled percentage` (0 or 100% state, where monthly
  averages approximate the percentage of time automatic adaptation was enabled)

All use `state_class: measurement`, so Home Assistant stores hourly long-term
statistics instead of relying solely on short-term Recorder state history.
These histories **begin at installation**, not retroactively.

The new third custom card discovers sensors and control entities automatically
from their unique Home Assistant names, displays current values, and draws
24-hour / 7-day / 90-day / one-year / three-year graphs using local Recorder
statistics. Click a settings value to open its native Home Assistant control.

Register the resource as a **JavaScript module**:

`/tado/x-settings-history-card.js?v=2026.11.8`

Add to a Lovelace dashboard:

```yaml
type: custom:tado-x-settings-history-card
title: Hot-water and heating optimisation
```

This also fixes a cumulative-sum calculation bug in the optional Vaillant
hourly heating allocation that could manifest when processing more than one
hour in a single batch. It does **not** change or recreate any original
Vaillant Recorder statistics.


This is the user's maintained **tado** custom integration fork, based on the
[original tado OAuth device-flow implementation](https://github.com/karlbeecken/ha-core/tree/tado-oauth-deviceflow/homeassistant/components/tado).
It keeps the core `tado` domain and existing HA config entries, entities and
tokens. Compatible with **PyTado 0.18.15**, retaining the token-persistence
fix used by earlier releases.

## New in 2026.11.7 — room schedules, DHW, OpenTherm settings, heating estimates

### 1. Home Assistant controls (tado X homes only)

When this integration loads, it adds home-level entities:

- **Number: DHW target temperature** (tested read: 62°C; allowed range for
  this installation: 35–70°C). Writes use the HOPS manual-control endpoint,
  so they may be treated as overrides. The app remains the authority.
- **Select: DHW operating mode** — Auto (resume), On (boost), Off.
  Your home's native DHW weekly schedule endpoint returned HTTP 404;
  the select will not create a missing native schedule.
- **Number: Maximum heating flow temperature** (configured read: 55°C;
  limits from API: 20–75°C).
- **Switch: Automatic flow temperature adaptation** (previous read: enabled).
- **Sensor: Optimised heating flow limit** (previous read: 49°C) — a
  **tado-calculated limit, NOT measured boiler flow temperature**.
- **Number per heating room: Estimated radiator capacity (kW)** — initially
  assumed at 1 kW per radiator valve (R2 has two). Edit after determining the
  installed radiator sizes. This weight affects NEW estimated allocations,
  not the real boiler or radiator configuration.

DHW and optimisation configuration are updated at most once every **30 minutes**
plus explicit writes. Room heating sensors still use the existing
**five-minute coordinator** with no additional cloud calls. A failed optional
settings read does not take down room heating.

### 2. Weekly heating schedule editor (adapted from Vipera Tuya Local editor)

The original Vipera UI is preserved in
[girtsn/tuya-local](https://github.com/girtsn/tuya-local).
This integration bundles a separate card adapted from its interaction model,
with tado's native variable-length schedule blocks (including times such as
23:40) rather than fixed hourly Tuya DP26 data.

- Choose any tado heating room, with actual room names.
- Review the complete seven-day plan.
- Edit heating target, OFF mode and block boundaries (5-minute increments).
- Split or merge time blocks, copy days, copy a day or full week to another room.
- Save explicitly: backend **GET -> compare old day signature -> POST single
  day -> GET confirmation**. If the schedule changed in the tado app before
  the write, the operation refuses to overwrite it. Multi-day saves can
  partially succeed; reload to reconcile.

**Add dashboard resource** (Settings → Dashboards → Resources, JavaScript module):

`/tado/x-schedule-card.js?v=2026.11.7`

Then add a manual Lovelace card:

```yaml
type: custom:tado-x-schedule-card
title: tado X weekly room schedules
```

The card invokes native `tado.x_list_rooms`, `tado.x_get_schedule`, and
`tado.x_save_day` actions. All tado cloud requests are initiated on demand.
If you have multiple configured tado X homes, set `config_entry: <entry-id>`
on the card.

### 3. Estimated heating gas consumed per room

The **existing myPyllant** fork already stores hourly energy profiles as
external Home Assistant Recorder statistics. This integration uses the unique
profile `("CONSUMED_PRIMARY_ENERGY", "HEATING")` — **Gas Heating**,
not total gas including domestic hot water.

For each completed hour it reads:

- Vaillant gas-heating INPUT energy (`mypyllant:` external statistic in Wh).
- Recorder's hourly heating-demand MEAN for each tado room (the
  existing `sensor.*_heating` entity; it is a room demand, not a TRV valve
  position).
- Optional rated radiator capacity per room. Default is 1 kW per detected
  VA-family radiator thermostat, not a hardware measurement.

Allocation formula per interval:

```text
weight(room) = mean_room_heating_demand_percent × configured_room_capacity_kw
gas_attributed_kwh(room) = Vaillant_Gas_Heating_kWh × weight(room) / sum(weights)
```

If any room demand history is missing or all weights are zero, the hour's
gas is **unallocated**, not falsely assigned to one radiator.
The approach gives *modelled shares of measured gas input*, not radiator
delivered heat. Valve positions and hydronic flow are still unknown.

Estimated results are published as **separate** `tado:` external hourly
statistics, preserving original Vaillant recorder statistics exactly.
This job runs at **HH:15** using local Recorder only; it makes
**zero additional tado or Vaillant cloud API requests**. Existing historical
statistics for allocation are append-only; they do not retroactively
recalculate when changing weights. Initial allocation can only cover hours
that have the required historic source statistics. The optional manual
`tado.x_compute_heating_allocation` action can process the previous 1–35 days,
with a `dry_run` option.

For the dashboard add another **JavaScript module** resource:

`/tado/x-heating-energy-card.js?v=2026.11.7`

Then:

```yaml
type: custom:tado-x-heating-energy-card
title: Estimated heating gas by room
```

Views: day, week, month, year, and **three years** (monthly trends).
Historic charts accumulate only data recorded or backfilled while the
corresponding room activity history exists.

### 4. Explicit Home Assistant actions

Read the full weekly schedule for a room (first retrieve the room IDs with
`tado.x_list_rooms`; replace the example ID):

```yaml
action: tado.x_get_schedule
data:
  room_id: 101
response_variable: room_schedule
```

Read current hot water and flow optimisation settings:

```yaml
action: tado.x_get_settings
response_variable: x_settings
```

Change the DHW target (example, NOT executed by installing the integration):

```yaml
action: tado.x_set_dhw_temperature
data:
  temperature: 60
```

Change maximum heating flow temperature and auto-adaptation (example):

```yaml
action: tado.x_set_flow
data:
  max_temperature: 55
  auto_adaptation: true
```

Estimate gas allocation on demand:

```yaml
action: tado.x_compute_heating_allocation
data:
  days: 3
  dry_run: true
response_variable: preview
```

All new write operations are explicitly requested by service/entity action.
Installation, restart, and periodic polling do **not change schedules,
domestic-hot-water settings or boiler configuration**.

## Safety and known limitations

- The HOPS API is unofficial and some write routes (notably DHW manual
  setpoint) are **not yet verified live on this installation**. Try a
  small, reversible change and verify in the tado app.
- Your home's `programmer/domesticHotWater/schedule` returned **404**, so
  native hot-water schedule editing is deliberately not offered.
- The OpenTherm feature reports flow **optimisation settings**, not live
  boiler burner modulation, temperature, pressure or valve positions.
- Do not rely on the modelled room gas allocation for billing or to detect
  individual faulty radiator valves.
- The `tado` custom domain replaces Home Assistant's built-in tado
  integration. Do not install a second plugin with the same domain.
- Original configuration entries, refresh tokens, old entities and
  statistics IDs are retained. Back up HA before replacing the custom
  integration; verify devices after restarting.

## Project lineage

Original fork: [oliviertassinari/tado-x](https://github.com/oliviertassinari/tado-x),
based on [karlbeecken's HA tado fork](https://github.com/karlbeecken/ha-core/tree/tado-oauth-deviceflow/homeassistant/components/tado).
New schedule editor reuses the interaction patterns of
[girtsn/tuya-local Vipera card](https://github.com/girtsn/tuya-local/blob/main/custom_components/tuya_local/www/vipera-schedule-card.js).
