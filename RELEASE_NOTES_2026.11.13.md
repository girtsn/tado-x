# tado X v2026.11.13 — restart-safe Eco/Top Boost and heating mode status

## Whole-home heating modes

The **Heating Overview** custom card now offers four explicit actions:

| Mode | Room behaviour | Flow adaptation | Automatic recovery |
| --- | --- | --- | --- |
| **Heating Off** | All rooms OFF / frost protection | Automatically enabled if needed | Remains off until changed |
| **Resume Schedules** | Cancels manual heating overrides, resumes schedules | **Always enabled / restored** | Immediate |
| **Eco Boost 30m** | tado X official all-room maximum-temperature boost | **Enabled** | Resume schedules + verify adaptation |
| **Top Boost 30m** | Same all-room maximum-temperature boost | **Disabled for the boost** | Resume schedules + re-enable adaptation |

Both Eco Boost and Top Boost store their expiry timestamps under Home
Assistant's persistent storage **before the cloud boost command**. If HA
restarts during the 30-minute period, the pending recovery is rescheduled;
if the deadline already passed during downtime, recovery starts promptly on
startup. A failed recovery is retried every five minutes. When possible,
the restoration is split into separate schedule and adaptation operations,
so a failed adaptation write cannot repeatedly reset manually edited room
schedules during recovery.

A long Home Assistant or network outage can postpone flow-adaptation
restoration until service is restored. tado's native Boost command itself
also has its own 30-minute timeout; only the Home Assistant automation of
adaptive flow depends on HA connectivity.

**Important:** Top Boost does not change the configured maximum heating
flow temperature. It allows tado to operate without automatic temperature
adaptation up to the existing configured maximum; it does not command the
boiler to a particular actual flow temperature.

## Current mode indicator

New Home Assistant sensor: **Heating home mode**.

- Shows `Schedules`, `Heating Off`, `Eco Boost`, `Top Boost`, or
  `Unknown` when no action has been issued yet.
- Includes a persistent UTC recovery deadline, pending recovery status,
  retry errors, and a countdown displayed in the Lovelace card.
- The **mode represents the last action requested through Home Assistant**,
  not a remotely verified tado household state. Changes initiated in the
  tado app or directly at a radiator may differ. The card explicitly labels
  this distinction.
- Mode state and boost deadline survive a Home Assistant restart.
- The card updates its countdown periodically while visible.

For programmatic control:

```yaml
action: tado.x_heating_quick_action
data:
  action: eco_boost   # off | resume | eco_boost | top_boost
```

To inspect scheduled recovery without accessing tado:

```yaml
action: tado.x_heating_mode_status
response_variable: heating_mode
```

The older `action: boost` remains a compatibility alias for `eco_boost`.

## Domestic hot water

Removed the experimental `DHW operating mode` selector from the tado
integration and the Overview dashboard. Your tado X home does not expose
a readable DHW programme, and the tado app offers a DHW target-temperature
setting rather than meaningful Auto/On/Off controls.

The **DHW target temperature** number and its long-term history remain
unchanged. Previous HOPS DHW service names are still present for backward
compatibility but are not shown on the dashboard; they remain experimental.

## Installation

Update HACS to `v2026.11.13`, restart Home Assistant, and update the
single changed dashboard JS resource:

`/tado/x-settings-history-card.js?v=2026.11.13`

No dashboard YAML replacement is needed: the original custom card type
automatically presents the new buttons and mode indicator. Existing
schedule/consumption JS resources and Vaillant statistics are unchanged.

The HOPS actions and scheduled recovery have offline regression tests.
The new Top Boost workflow has **not** yet been tested on the real tado
installation: use Eco Boost or Resume first, and check the tado app after
the first Top Boost activation.
