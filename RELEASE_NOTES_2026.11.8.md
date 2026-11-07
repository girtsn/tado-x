# tado X v2026.11.8 — history dashboard and gas allocation fix

Maintenance and dashboard release. Inherits all functionality from v2026.11.7:
weekly schedule editor, room capacities, DHW control, flow optimisation, and
Vaillant gas-input estimates. Existing tado data and settings remain unchanged.

## New permanent Home Assistant histories

- DHW target temperature history — measurement sensor, °C
- Maximum flow temperature history — measurement sensor, °C
- Optimised heating flow limit — existing measurement sensor, °C
- Flow adaptation enabled percentage — new measurement sensor, 0/100%

These are explicitly **configuration/optimisation readings**, not measured
boiler temperatures, hot-water tank temperature or valve positions. Recorder's
long-term statistics allow three-year graphs going forward. No historical
measurements are invented.

New auto-discovering card, with current controls opening their native HA
more-info dialogs and historical plots at 24-hour, seven-day, 90-day,
one-year and three-year scales. Register as JavaScript module:

`/tado/x-settings-history-card.js?v=2026.11.8`

Then in a dashboard:

```yaml
type: custom:tado-x-settings-history-card
title: Hot-water and heating optimisation
```

The card resolves entities by unique English suffix, avoiding dependence on
home-name prefixes. If multiple tado homes expose identically named entities,
customisation may be necessary.

## Consumption bugfix

The v2026.11.7 estimate allocation assumed an attribute on Home Assistant's
`StatisticData` TypedDict during multi-hour batches. This release uses its
dictionary key. Adds a multi-hour cumulative-sum regression test. Estimated
gas kWh remain separate `tado:` external statistics and never overwrite
myPyllant originals.

## Installation

Update the existing custom HACS integration from
`https://github.com/girtsn/tado-x` to **v2026.11.8**, restart Home Assistant,
then register the three dashboard JS resources documented in README.md.

This release does **not** perform any write to boiler control, DHW or room
schedules during installation or normal polling. New HOPS setting write
endpoints remain experimental until verified live on the actual installation.
