# tado X v2026.11.11 — investigate unallocated heating gas

## Read-only diagnostic (main improvement)

A new `tado.x_diagnose_unallocated_heating` action investigates gas input
assigned to Unallocated by the Vaillant/tado allocation model.

In Home Assistant **Developer Tools → Actions**, run:

```yaml
action: tado.x_diagnose_unallocated_heating
data:
  days: 35
  limit: 30
response_variable: diagnosis
```

The response separates **two causes** which previously looked identical:

- `missing_or_invalid_room_demand`: one or more room statistics missing
  or outside 0–100%; the model conservatively assigns the **entire hour's
  gas input** to Unallocated, even if another room was heating.
- `all_rooms_zero_demand`: all ten rooms had available 0% mean demand
  in that hour, yet Vaillant reports positive heating-gas input.

It reports totals and counts per cause, missing sensor names, daily
unallocated amounts, the 30 highest-gas unallocated hours with Brussels
local timestamps, other rooms with active demand, and whether a room had
demand during the adjacent hours (a clue for delayed/overlapping boiler
activity, not proof).

This diagnostic uses existing local Home Assistant Recorder hourly data,
**makes no cloud calls and writes no statistics or device settings**.
Review results before changing any formula or past estimate.

## Dashboard wording fix

Maintenance release for diagnosing gas allocation and correcting the custom Lovelace consumption card.

- Corrects an **obsolete footer** in `tado-x-heating-energy-card.js`
  that still said room capacity defaults to 1 kW per radiator.
- Clearly identifies the actual model: 11 installed physical radiators
  in 10 tado heating rooms, rated nominal **25.748 kW** at EN442
  75/65/20°C (Delta-T50).
- Explains that estimated per-room Vaillant heating-gas **input** is weighted
  by tado room heating demand and each room's aggregate rated radiator output,
  not actual measured heat delivered at a lower boiler flow temperature.
- Keeps the explanation of Unallocated gas, which arises where no room
  demanded heating or demand measurements were incomplete.
- No calculation change, no additional tado cloud requests, no boiler
  settings changed, no prior Recorder statistics modified.

Installation: Update HACS to `2026.11.11`, restart Home Assistant and
refresh the browser or mobile app. Resource cache busting is recommended:

`/tado/x-heating-energy-card.js?v=2026.11.11`

The other two existing custom JavaScript card resources remain compatible.
