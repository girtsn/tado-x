# tado X v2026.11.18 — Energy-style calendar navigation and gas sidebar icon

This maintenance feature release improves the existing **managed Heating
panel's Vaillant Consumption card** as well as the optional traditional
Lovelace Consumption card.

## Date navigator — no more misleading 33-day 'Month'

The Consumption card now provides:

- **Day** (calendar day, hourly trends)
- **Week** (Monday–Sunday; daily trends)
- **Month** (actual calendar month; daily trends)
- **Year** (January–December; monthly trends)
- **3 years** (trailing 36 calendar months ending in the selected month,
  with 3-year block navigation; monthly trends)
- **Custom** start/end dates (inclusive; day or monthly trend as appropriate)
- Previous / next arrows, a date picker and a Current shortcut.

The same date selection controls the room bars, allocated/unallocated totals
and consumption trend; they can now be compared on matching calendar dates
with tado's Energy IQ and Vaillant's records.

The chosen period AND selected date are saved in the browser/app's local
storage and restored when returning to the panel. This is per device/browser
and does not synchronise choices between different phones or PCs.

The local date range is interpreted in **Home Assistant's configured timezone
(default Europe/Brussels)**, correctly handling DST days of 23 or 25 hours.
No future consumption or missing Recorder history is invented. Large year/
3-year ranges request efficient monthly statistics; partial first/last months
are calculated using actual hourly Recorder data.

The service `tado.x_heating_allocation_history` remains backwards-compatible
when called without dates. Optional `start_date` and `end_date` are now
both accepted (YYYY-MM-DD, inclusive), e.g.:

```yaml
action: tado.x_heating_allocation_history
data:
  period: month
  start_date: "2026-11-01"
  end_date: "2026-11-07"
response_variable: comparison
```

This action reads Recorder statistics only and does not rewrite the Vaillant
source or previously recorded tado per-room allocation estimates. The
pre-3-November 2026 historic Vaillant daily backfill is still synthetic at the
hourly level; do not interpret historical hourly room results as boiler-run
timings.

**The 3-year selection does not manufacture history**: room allocation
statistics only appear in time ranges where they actually exist.

## Sidebar icon

The integration-managed `tado X Heating` panel now registers itself with
`mdi:gas-burner` rather than `mdi:home-thermometer`, representing gas heating.
This changes after the HACS update and Home Assistant restart. The icon
for a manually created Lovelace dashboard must instead be set manually under
**Settings → Dashboards → choose dashboard → Icon** to `mdi:gas-burner`.

## Upgrade

Update HACS to **2026.11.18** and restart Home Assistant. The
integration-managed panel imports its own versioned resources automatically
(no YAML or resource registration needed).

If instead you still use a manually created Heating Lovelace dashboard,
update the card resource URL to:

`/tado/x-heating-energy-card.js?v=2026.11.18`

No changes to any hot-water, radiator or whole-home heating controls.
