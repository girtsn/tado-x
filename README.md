# tado X integration — Home Assistant fork

## v2026.11.19 — cloud API connectivity and stale-update detection

Read-only **tado X API cloud connection state**, **tado X settings cloud
connection state** and **tado X last successful update** entities are added
under the tado home device. The main API and the separately polled DHW/flow
settings API are monitored independently, including stale data (15 minutes
and 95 minutes respectively). The diagnostics continue to report a state even
if the coordinator fails; last-success timestamps remain visible.

The integration-managed Heating panel displays live cloud health above both
tabs; the standalone heating-history card includes the same status strip.
These status indicators use only Home Assistant state and do not poll the
tado cloud from the browser.

Update through HACS and restart Home Assistant. To add offline/recovered
email alerts, **replace the existing Home Assistant automation manually**
with [examples/device_availability_dynamic_email.yaml](examples/device_availability_dynamic_email.yaml).
The example preserves the existing Foscam/TV exclusions, 5-minute delay,
and recovery-only-after-outage logic, while monitoring *both* tado API
sensors even though they share one device. The HACS integration cannot
change user-owned Home Assistant automations automatically.

The diagnostic sensors can report cloud loss while HA is running and the
integration has completed its initial setup. An outage that prevents the
integration from loading at all on HA startup requires a separate
Home Assistant startup/integration-health watchdog.


## v2026.11.18 — one history date picker across Heating cards

The managed **tado X Heating** dashboard has one Energy-style date picker for all historical charts (including **Last 3 years** and custom dates), and the individual period button groups have been removed. Standalone cards use the same calendar picker instead of period buttons. JavaScript dependencies use manifest-versioned URLs, and the sidebar icon now uses a gas burner. Update through HACS and restart Home Assistant.

## v2026.11.17 — managed Heating panel cache busting

The automatically installed `tado X Heating` sidebar panel now uses a
manifest-versioned module URL so new HACS releases refresh its frontend
JavaScript automatically after a Home Assistant restart / page reload.
`frontend` and `http` are explicit integration dependencies. No
dashboard YAML, frontend Resources registration, automations or helpers
have to be copied again. The original user-created `Heating` dashboard
remains unchanged.



## v2026.11.16 — self-updating Heating panel (no YAML maintenance)

The integration automatically installs a **tado X Heating** sidebar panel
at `/tado-x-heating` using Home Assistant's custom-panel extension. The panel
bundles the three existing custom cards, including heating flow/DHW controls,
home heating modes (Off, Resume, Eco Boost and Top Boost), live room schedule
status, the 30-minute recovery countdown, and the weekly editor.

The **Vaillant/myPyllant consumption view appears automatically only when
the existing household energy option is enabled**. No separate dashboard
definition, Lovelace resource registration, helper entity or YAML automation
is required for the managed panel. This gets updated through normal HACS
releases plus a Home Assistant restart.

**Existing manually built dashboards are not replaced.** If you already
created a `Heating` Lovelace dashboard, the new `tado X Heating` panel
is a second sidebar item. Verify the managed panel, then optionally hide
the older one in Home Assistant's sidebar controls.

For installations that prefer a traditional editable Lovelace YAML dashboard,
[examples/heating_dashboard.yaml](examples/heating_dashboard.yaml) remains a
single canonical example with a conditional Vaillant section controlled by
the read-only `binary_sensor.tado_x_vaillant_energy_enabled`. This sensor
mirrors the sole optional household energy setting; it does not create
another option.

**Heating mode recovery is already implemented inside the integration**
with persistent storage, so no external Home Assistant automation or helper
has to be installed. Independent user automations/helpers are deliberately
left alone during updates.



## v2026.11.15 — tado X for everyone; household Vaillant features opt-in

**All tado X controls remain available to every tado X user without enabling
a switch**: hot-water target, flow-temperature settings/history, room schedule
editor, room manual-override state, whole-home Heating Off/Resume/Eco Boost/
Top Boost and persisted 30-minute boost recovery.

After any whole-home action, its timed recovery, or saving a room heating
schedule, the coordinator queues a **3-second delayed readback of all room
states**, updating the Heating dashboard without waiting for the regular
5-minute poll. The readback consumes normal tado API requests once, and rapid
actions are coalesced.

Only **Household-specific Vaillant/myPyllant gas allocation and installed
radiator inventory** is optional, disabled by default for new installations.
Enable it under **Settings → Devices & services → tado → Configure**.
Existing homes with recorded radiator-weighted allocation statistics are
automatically recognised and have the option preserved. Other installations
need not have myPyllant installed and no Vaillant allocation runs unless this
single option is enabled.

The [canonical Heating dashboard YAML](examples/heating_dashboard.yaml)
includes universal tado X controls and schedules for all homes, and shows the
optional Vaillant consumption section only when the integration's read-only
household energy status sensor reports `on`. The managed `tado X Heating`
sidebar panel avoids needing this YAML at all.

The optional consumption card and included hardcoded radiator data remain
visible in this public source repository; opting out prevents their runtime
use, not access to the source code.

The built-in dashboard cards have not changed in this release; previous
registered JavaScript resources still work without cache busting.



## v2026.11.14 — live tado X schedule-mode detection

The **Heating home mode** sensor and Overview indicator now use the ten actual
tado X room states, not only the last button pressed in Home Assistant:

- **Following Schedules** when all ten rooms report Smart Schedule
- **Manual Override (N)** when one or more rooms have an active manual setting
- **Heating Off** when all ten rooms report manual Off
- **Room state incomplete** if any room's status is unavailable
- **Eco / Top Boost** with the stored 30-minute recovery countdown when a
  Home Assistant boost is pending and the room states confirm manual control.

The latest reported schedule state can differ from the last action requested
via Home Assistant if someone changes a radiator or the tado app. The
integration uses `PyTado.TadoXZone.overlay_active` which reflects
`manualControlTermination`, rather than comparing temperatures to scheduled
setpoints.

A separate **Heating schedule control** sensor is available for each tado
room, showing **Smart Schedule / Manual Override / Unknown**. These are
room-level indicators: the two radiator valves in the attic bedroom share a
single room control state. It uses only the normal 5-minute room poll.

A new read-only Developer Tools action reports everything:

```yaml
action: tado.x_room_schedule_status
response_variable: room_schedules
```

**Resume Schedules** is greyed out when all rooms follow schedules, adaptive
flow is enabled and there is no pending boost. A manual room override, a
disabled adaptation setting or an active saved boost makes it available.
An unknown room is not silently assumed to be manually controlled.

Register the updated history/Overview module at
`/tado/x-settings-history-card.js?v=2026.11.14`.
The existing Heating dashboard YAML remains compatible; this release
does not change any device setting during installation.



## v2026.11.13 — persisted Eco Boost, Top Boost, and current HA heating mode

New whole-home heating choices:

- **Heating Off**: all room heating OFF (frost protection); supersedes
  pending boosts and ensures adaptation is enabled.
- **Resume Schedules**: cancels manual room heating overrides and **always**
  re-enables automatic flow-temperature adaptation if tado reports it OFF.
- **Eco Boost 30m**: official tado X all-room boost with adaptation enabled,
  automatically restores schedules after 30 minutes.
- **Top Boost 30m**: same room boost, but **disables automatic flow adaptation
  for 30 minutes**, then resumes all schedules and re-enables adaptation.

Both boost deadlines are persisted in Home Assistant's storage, and recovery
resumes after a Home Assistant restart even if the deadline expired during
downtime. Recovery failures retry every five minutes; Home Assistant must
eventually be running and connected to tado to restore adaptation. The
configured max flow-temperature limit is not increased by Top Boost.

The new **Heating home mode** sensor and dashboard mode strip show the last
mode requested *through Home Assistant*, the boost's remaining time, and
recovery warnings. They cannot guarantee the current app/valve state if the
mode was changed outside Home Assistant. The JS card automatically exposes
these features after installing v2026.11.13; no dashboard YAML replacement.

```yaml
action: tado.x_heating_quick_action
data:
  action: top_boost  # also off / resume / eco_boost
```

The old `action: boost` still means Eco Boost for compatibility.

The old DHW Auto/On/Off selector is removed because no meaningful DHW
schedule was exposed for the user's tado X home. DHW temperature remains
available and independently editable. The legacy experimental DHW services
remain for compatibility.

The only JS resource that needs cache busting is
`/tado/x-settings-history-card.js?v=2026.11.13`.



## v2026.11.12 — three whole-home heating quick actions and a single temperature chart

The Overview card now offers **Heating Off**, **Resume Schedules**, and
**Boost 30 min** for all heating rooms, with explicit confirmation dialogs.
Only the user can trigger these operations. They use one tado X HOPS request
each and do not directly alter domestic hot water, boiler settings or the
automatic flow-temperature adaptation toggle.

Home Assistant Developer Tools equivalents:

```yaml
action: tado.x_heating_quick_action
data:
  action: off  # or resume / boost
```

Heating Off retains frost protection, Resume cancels manual heating overrides,
and Boost sets maximum room temperatures for 30 minutes, after which the
schedules resume. These actions follow tado X's app Quick Actions; the
undocumented HOPS requests are not yet live-tested on this installation.

The rebuilt history card puts **heating flow first**, followed by hot water,
then a single graph with selectable maximum flow, tado-optimised flow,
DHW target, and outside temperature. The awkward "Adaptation enabled time"
label is replaced with **Automatic flow adaptation** (On/Off + optional
historical enabled percentage). It uses the existing tado weather
outdoor-temperature sensor by preference, or an explicitly configured outdoor
entity (no extra cloud call):

```yaml
type: custom:tado-x-settings-history-card
title: Heating flow and hot water
# outdoor_entity: sensor.actual_outdoor_temperature
```

A full dashboard example, ready to paste into Home Assistant's **Raw
configuration editor**, is at [examples/heating_dashboard.yaml](examples/heating_dashboard.yaml).
Its tab order is **Overview → Consumption → Schedules**.

Register/update the card JavaScript module with
`/tado/x-settings-history-card.js?v=2026.11.12`.
Only this card JS changed; the schedule and consumption resources can retain
their existing working registration URLs if preferred.

**Note:** Vaillant historical hourly statistics derived from daily
backfill are not measured burner intervals. Per-room pre-November 2026
allocations are provisional until we introduce a separate daily-weighted
allocation model. This release leaves the existing statistics unchanged.


## v2026.11.11 — diagnose unallocated Vaillant heating-gas input

Use this read-only Home Assistant action to explain which of the 35 days'
hours produced **Unallocated** gas in the Vaillant/tado room split:

```yaml
action: tado.x_diagnose_unallocated_heating
data:
  days: 35
  limit: 30
response_variable: diagnosis
```

The result has `causes.missing_or_invalid_room_demand` and
`causes.all_rooms_zero_demand` with separate hours and kWh, a room-by-room
missing-data count, date breakdown, and highest-energy hours in Brussels
local time. For zero-demand hours, adjacent-hour activity is reported to
help investigate timing differences. No historical statistics, radiator
ratings or tado/Vaillant settings are modified.

The consumption card footer now correctly states **11 radiators, 10 rooms,
25.748 kW at EN442 75/65/20°C**, rather than the obsolete 1 kW-per-valve
default.


## v2026.11.10 — all 10 actual tado room names now match automatically

The live `tado.x_radiator_capacity_report` identified four additional exact
name variants: `1fl bedroom streetside` (tado 7 → physical R06, 2.424 kW),
`1fl bedroom yardside` (tado 8 → R05, 2.424 kW), `1fl bedroom small`
(tado 9 → R07, 1.449 kW), and `0fl hallway` (tado 5 → R02, 1.643 kW).
These are now supported as built-in aliases.

After updating and restarting, the radiator report should show **10 matched
tado rooms and 25,748 W nominal total**, with the attic bedroom's two
physical radiators R09 and R10 combined at 6.538 kW. Existing manual
capacity overrides are preserved unless `tado.x_apply_radiator_capacities`
is run with `overwrite_existing: true`. This update changes **no tado or
Vaillant device setting**.


## v2026.11.9 — real radiator inventory, not one kilowatt per thermostat

This update replaces the earlier nominal **1 kW per tado radiator thermostat**
default with capacity weights from the installed radiator specifications,
using catalogue EN442 rated outputs at **75/65/20°C (Delta-T50)**.
The physical radiator IDs **R01–R11** are NOT tado room IDs **R1–R10**.
The two radiator thermostats in one tado room correspond to the **attic
bedroom's R09 and R10**, not physical radiator R02.

| Physical radiator | Floor, room | Series, type, H×L | Nominal output |
| --- | --- | --- | ---: |
| R01 | 0fl Living room | Uni.8 T33, 300×3000 mm | 3993 W |
| R02 | 0fl Entrance hallway | Uni.8 T33, 900×500 mm | 1643 W |
| R03 | 0fl Kitchen | Uni.8 T33, 500×1000 mm | 2075 W |
| R04 | 0fl Toilet | Uni.8 SP-08 T21, 900×400 mm | 721 W |
| R05 | 1fl Yard-side bedroom | Compact 4 T33, 500×1200 mm | 2424 W |
| R06 | 1fl Street-side bedroom | Compact 4 T33, 500×1200 mm | 2424 W |
| R07 | 1fl Small bedroom | Compact 4 T22, 500×1000 mm | 1449 W |
| R08 | 1fl Bathroom | Compact 4 T33, 500×600 mm | 1212 W |
| R09 | 2fl Attic bedroom, radiator 1 | Uni.8 SP-08 T33, 700×1200 mm | 3269 W |
| R10 | 2fl Attic bedroom, radiator 2 | Uni.8 SP-08 T33, 700×1200 mm | 3269 W |
| R11 | 2fl Attic bathroom | Uni.8 SP-08 T33, 700×1200 mm | 3269 W |
| **Total** | **10 rooms, 11 radiators** | | **25748 W** |

**Resulting attic bedroom room weight:** R09 + R10 = **6.538 kW**.
R11's **3.269 kW** belongs to the separate attic bathroom.

### Inspect the live room mapping before modifying weights

Run this in **Developer Tools → Actions**:

```yaml
action: tado.x_radiator_capacity_report
response_variable: radiator_report
```

It reports real tado room IDs and names, the physical Rxx radiators proposed
for each, the nominal EN442 W, detected valve count, any existing HA
number-entity override and any mismatch. Mapping uses conservative exact
name aliases; it does **not** assume physical R02 corresponds to tado R2.

If a room is not matched, obtain the real tado room IDs using
`tado.x_list_rooms`, then explicitly map it. Example (replace **999**
with the actual tado room ID returned by Home Assistant):

```yaml
action: tado.x_assign_radiator_room
data:
  room_id: 999
  physical_room: attic_bedroom
```

Available physical-room groups are:
`living`, `entrance`, `kitchen`, `toilet`, `yard_bedroom`,
`street_bedroom`, `small_bedroom`, `bathroom_1fl`,
`attic_bedroom`, `attic_bathroom`.
Set `physical_room: auto` to remove a manual assignment.
A group can only be explicitly assigned once.

Matched rooms immediately show their nominal power on the existing
**Estimated radiator capacity** `number` entities (precision 0.001 kW =
1 watt). Existing manually saved number-entity values continue to override
automatic defaults.

Use the following action to **preview** the values that would be stored
locally, without making any change:

```yaml
action: tado.x_apply_radiator_capacities
data:
  dry_run: true
  overwrite_existing: true
response_variable: planned_wattages
```

When the mapping and watts are correct, change `dry_run` to `false` to
persist the rated output for mapped rooms. `overwrite_existing: false`
(default) preserves any previously set manual wattage; use `true` to
replace legacy 1 kW manual values with the catalogue output. This updates
**only Home Assistant's room weights**, not radiator valves, tado schedules,
boiler setpoints or Vaillant measured statistics.

### Allocation data compatibility

To avoid mixing the original equal-capacity model with the new rated-output
model, new gas-input estimates are published to separate
`tado:x_radiator_weighted_gas_heating_v2_*` statistic IDs.
Old `tado:x_estimated_gas_heating_*` values are **not deleted or rewritten**.
The custom consumption card now reads the v2 series and will build its own
history from hours where rated output and room demand are available.
If rooms cannot be mapped without ambiguity, estimation pauses and the
capacity report explains why. Don't rely on these allocated kWh for billing:
the kW ratings are standard-test output, not measured delivered radiator
heat, and heating-demand % is not physical valve travel.


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
