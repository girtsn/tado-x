# tado X v2026.11.9 — real radiator ratings and correct per-room weights

This release corrects the equal-1kW assumptions in the room heating-gas
allocation model, without changing tado cloud settings or Vaillant data.

## Confirmed physical inventory

**R01–R11 are 11 physical radiators, not the 10 tado room IDs.**

- 0fl: living 3993 W; entrance 1643 W; kitchen 2075 W; toilet 721 W
- 1fl: yard bedroom 2424 W; street bedroom 2424 W; small bedroom 1449 W;
  bathroom 1212 W
- 2fl: attic bedroom **two radiators**, R09 + R10 = **6538 W**;
  attic bathroom R11 = **3269 W**
- Total **25,748 W nominal at EN442 75/65/20°C Delta-T50**.

These are reference radiator heat outputs, *not measured gas consumption or
valve positions*, and physical heat output varies with system water temperature.

## Home Assistant improvements

- Existing **Estimated radiator capacity** number entities now default to
  exact catalogue-derived room totals (0.001 kW resolution) whenever the
  tado room name matches a uniquely identifiable room and radiator count.
- New read-only `tado.x_radiator_capacity_report` action shows each tado
  room, physical radiator IDs, manufacturer type/dimensions, rated watts,
  detected VA thermostat count, status and saved manual overrides.
- New `tado.x_assign_radiator_room` action maps a *real tado room ID*
  to a named radiator room (`attic_bedroom`, `attic_bathroom`, etc.) when
  actual tado room names differ from the inventory.
- New `tado.x_apply_radiator_capacities` action previews changes by default.
  With `dry_run: false`, it stores matched rated outputs into local HA
  options. Existing saved values are retained unless
  `overwrite_existing: true` is provided.
- A mismatched/missing mapping now pauses automatic gas allocation instead
  of silently guessing 1 kW per radiator.
- Gas allocation writes NEW `tado:x_radiator_weighted_gas_heating_v2_*`
  Recorder statistic IDs; previous equal-weight estimate series are preserved
  untouched and remain available for comparison.
- No change to native tado DHW controls, flow optimisation or weekly schedules.

## First check

After updating the existing HACS integration and restarting Home Assistant:

```yaml
action: tado.x_radiator_capacity_report
response_variable: radiator_report
```

Confirm that **one tado room** maps to physical `R09` and `R10` together,
with `capacity_kw: 6.538`, and that **another** maps to `R11` at
`capacity_kw: 3.269`. Do not equate tado R2 with physical R02.

For the complete table, safe assignment steps, and how to update local wattage
number entities without affecting boiler settings, see README.md.
