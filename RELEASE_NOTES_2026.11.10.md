# tado X v2026.11.10 — match all actual radiator-room labels

This release adds exact, unambiguous aliases for the four genuine tado X room
names that were missing from the v2026.11.9 radiator capacity report:

| Real tado room ID | tado room name | Physical radiator | EN442 rated output |
| --- | --- | --- | ---: |
| 7 | 1fl bedroom streetside | R06 (street-side bedroom) | 2.424 kW |
| 8 | 1fl bedroom yardside | R05 (yard-side bedroom) | 2.424 kW |
| 9 | 1fl bedroom small | R07 (small bedroom) | 1.449 kW |
| 5 | 0fl hallway | R02 (entrance hallway) | 1.643 kW |

The other six physical room mappings were already correct. The resulting
installation is **10 matched heating rooms, 11 physical radiators, 25,748 W
rated EN442 output**. Attic bedroom tado room ID 11 maps to **R09 + R10**
(6.538 kW), *not* physical radiator R11; tado room 10 (attic bathroom) maps
to physical R11 (3.269 kW).

## Installation and verification

Update the existing HACS installation to v2026.11.10 and restart Home Assistant.

Run:

```yaml
action: tado.x_radiator_capacity_report
response_variable: radiator_report
```

Expected: `matched_rooms: 10`, `matched_rated_w: 25748`, and all ten
rooms `status: matched`. Their editable capacity-number entities now
default to the exact kW ratings unless they have **existing manual
overrides**, which remain untouched.

To persist all ten catalogue values locally, even where earlier manual
values were set, run:

```yaml
action: tado.x_apply_radiator_capacities
data:
  dry_run: false
  overwrite_existing: true
response_variable: result
```

The value changes only local Home Assistant heating-gas allocation weights.
No tado cloud schedules, boiler settings or Vaillant measured source data
are modified. To inspect which values would be written, use
`dry_run: true`.

The model continues to estimate proportional shares of *gas input*, not
physical radiator heat. EN442 output is a reference rating at 75/65/20°C,
and changes to room capacity weights only apply to newly computed v2
allocation statistics. Existing historical estimated statistics are not
overwritten.

This release also includes a regression test using the user's actual
reported room names and tado room IDs to prevent future mismapping.
