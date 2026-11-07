# tado X v2026.11.15 — fast post-action readback; universal tado X, optional Vaillant extras

## Immediate heating-state readback

The main Tado X coordinator now schedules a **coalesced room-state refresh 3
seconds after a heating write**. This applies to:

- Heating Off, Resume Schedules, Eco Boost and Top Boost
- The persisted 30-minute boost recovery actions
- Saving a room's heating schedule via the custom schedule editor

The readback fetches the actual tado room states including
`manualControlTermination`; Home Assistant's existing **Heating home mode**
and per-room **Heating schedule control** sensors update without waiting for
the usual five-minute coordinator poll.

**This readback is not a guarantee of immediate physical valve movement.**
If the HOPS backend has not yet applied an action, the normal 5-minute poll
still updates it. A failed readback logs a warning but does not claim the
original control command failed. Multiple rapid writes cancel and replace a
pending readback, avoiding extra polling after each individual action.
A single readback currently uses the standard PyTado get-zone-state routine
and can issue multiple room API calls; it is **not free of tado cloud API
usage**. It occurs only after user commands or previously requested timed
recoveries, not on a continuous new polling interval.

## One optional household integration feature; all tado X controls included

For compatibility with users of this public fork:

### Always on for tado X

- All standard tado Home Assistant climate and room entities
- Home-wide Heating Off, Resume Schedules, Eco Boost and Top Boost
- Restart-safe Eco/Top 30-minute recovery and current-mode sensor
- Per-room schedule/manual-override sensors, HOPS reading and editing
- Hot-water temperature, flow maximum, adaptive flow switch, history
- All three custom card JS files remain available for dashboard authors
- Short post-action room-state readback

**No advanced tado X opt-in switch is needed.**

### Optional household-specific Vaillant / radiator functionality

Only the configuration checkbox
`x_household_energy` enables:

- Physical radiator inventory with specific installed rated powers and
  name matching, and the per-room estimated radiator-capacity number entities
- Vaillant/myPyllant gas-heating allocation, hourly automatic statistics,
  historical consumption comparison and diagnostic actions
- The custom consumption card remains a separate opt-in dashboard component,
  and is useful only if the matching myPyllant source is installed

**Fresh installations have the household feature OFF by default**.
The integration options show one checkbox under
**Settings → Devices & services → tado → Configure**.

The repository now has **two distinct dashboard templates**:
- `examples/heating_dashboard.yaml` — generic tado X Overview and Schedules,
  with no Vaillant or installed-radiator assumptions.
- `examples/heating_dashboard_household_vaillant.yaml` — optional home
  implementation with Vaillant/myPyllant consumption and rated radiator
  inventory, meant only for homes explicitly enabling that feature.

Existing dashboards in Home Assistant are never rewritten by the update.

### Existing installation migration

The integration config-entry version advances from 2 to 3. Existing homes
retain all tado X capabilities, automatically.

For existing homes that already published v2 radiator-weighted heating
allocation statistics into Home Assistant Recorder, a one-time,
**per-tado-home statistic-ID** check preserves the household-energy feature as
enabled. No home/account ID or address is baked into the feature flag. If
the existing Recorder read fails during startup, the household feature
remains disabled but the migration check is retried next restart. You can
always enable it manually in options. The previous per-room capacity and
physical-room mapping options are preserved when saving other options.

## Installation

Update HACS to **v2026.11.15** and restart Home Assistant. No dashboard YAML
or JavaScript resource update is needed: the three custom cards are unchanged
by this release.

To check the optional feature:

- Go to **Settings → Devices & services → tado → Configure**.
- Leave **Vaillant/myPyllant household energy** checked on installations
  using this radiator model; leave it off elsewhere.
- The regular tado X settings and heating modes are available either way.

No heating changes are sent to devices during the installation or migration.
Only already-authorized, persisted boost recoveries can run automatically.

## Limitations and data safety

The house-specific radiator inventory values remain in the public source
code behind the disabled-by-default feature switch; the checkbox controls
runtime creation/use, **not whether the source code itself is public**.
Releasing a generic user-configurable radiator inventory, rather than
shipping one household's specifications, is a distinct future improvement.

The Vaillant backfilled hourly consumption prior to 3 November 2026 was
synthetically spread from daily measurements; its older per-room allocations
are provisional. This release does not alter previous Recorder statistics.
