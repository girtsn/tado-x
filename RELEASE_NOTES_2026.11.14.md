# tado X v2026.11.14 — live schedule and manual-override status

## Live schedule status, per room

The integration now uses **PyTado 0.18.15** room status already fetched in
the usual 5-minute poll: `TadoXZone.overlay_active`, derived from
`manualControlTermination` on the HOPS room state. It does **not** compare
temperatures with schedules, since the same target temperature can be either
scheduled or manually set.

Each of the 10 tado heating rooms gets a **Heating schedule control** sensor:
- **Smart Schedule**: reported room has no active manual override
- **Manual Override**: a manual control (including manual Off) is in effect
- **Unknown**: state cannot be confirmed

The sensors include the room ID, whether a manual override is active and
the reported termination type. These report status **per tado room**, not
individual radiator valves. The two 2fl bedroom radiator valves belong to
one room and therefore share one schedule status.

A new read-only Home Assistant action returns all rooms and the observed
whole-home mode:

```yaml
action: tado.x_room_schedule_status
response_variable: room_schedules
```

No additional cloud calls are made.

## Current-mode indicator uses observed room state

The existing **Heating home mode** sensor and Heating Overview card now
distinguish:

- **Following Schedules:** all rooms report following Smart Schedule
- **Manual Override (N):** some rooms report manual temperature or Off
- **Heating Off:** every room reports a manual Off
- **Room state incomplete:** at least one room status is unknown
- **Eco Boost / Top Boost:** a saved HA boost timer is pending, and room
  states are consistent with active manual control; the 30-minute recovery
  countdown remains visible

The status is derived from tado room polling, rather than blindly trusting
the last HA button press. This lets the indicator reflect external app or
thermostat changes after the next normal poll. The stored last-action mode,
boost deadlines and recovery errors are retained separately in attributes.
During the short delay between a command and the next room poll, the card
may show the previous reported room state; any pending HA recovery timer
remains separately visible.

## Resume Schedules is context-sensitive

The **Resume Schedules** button on the Overview card is disabled if:
- all rooms report following their Smart Schedules, and
- automatic flow adaptation is known to be enabled, and
- no HA boost is awaiting recovery.

It is enabled when a room is **known to have a manual override**, when
automatic flow adaptation is known disabled, or when a saved boost is
still pending. Unknown room status alone is *not* evidence of an override.

When used, Resume Schedules still cancels all room overrides and always
ensures automatic flow-temperature adaptation is re-enabled, as implemented
in v2026.11.13.

This status remains a read-only observation of cloud data and is updated on
the normal poll, not necessarily immediately after pressing a tado button.
A single tado room may have two radiator valve devices.

## Installation

Update the existing HACS tado X integration to **v2026.11.14** and restart
Home Assistant. Bump the Overview card resource to:

`/tado/x-settings-history-card.js?v=2026.11.14`

The same Heating dashboard YAML and other two card resources continue to
work. No changes to heating schedules, controls, flow settings, Vaillant
energy statistics, or radiator capacities are made during this update.

Regression tests cover scheduled Off versus manual Off, manual setpoint equal
to the scheduled setpoint, mixed room states, unknown/unavailable rooms,
all-off, app-initiated return to schedules and a pending Eco/Top Boost.
