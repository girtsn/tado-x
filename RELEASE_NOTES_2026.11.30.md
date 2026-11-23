# tado X 2026.11.30 — Locate first reliable-looking Vaillant hourly day

**New read-only Home Assistant Developer Tools action:** `tado.x_scan_vaillant_hourly_quality`.

- Scans the **original myPyllant Gas Heating hourly Recorder statistic** for the last 120 completed days by default (configurable to 3–365 days).
- Groups data into genuine Home Assistant-local calendar days, including 23- and 25-hour daylight-saving days.
- Reports `first_complete_nonuniform_day`: the first full day where hourly heating gas values differ meaningfully.
- Flags completed days with **positive, almost identical hourly amounts** as `uniform_positive_suspected_backfill`: possible synthetic daily consumption spread over the day.
- Reports `last_uniform_positive_day` and `candidate_cutoff_day`: the first sustained run of consecutive nonuniform days after the last suspicious uniform-positive day in the scan.
- Zero-gas days are classified separately as `no_heating`, and incomplete days never qualify as real hourly data.
- Output includes `transition_window` with local dates, hourly counts, totals, minimum and maximum hourly kWh, and Wh spread for contextual verification.
- Optional `tolerance_wh` (default **1 Wh**) and `confirmation_days` (default **3**) tune detection.
- Read-only: **does not delete, adjust, or backfill any Vaillant or Tado statistics and does not enforce a history cutoff.**
- Regression tests cover synthetic flat/varied transitions, Belgian DST, missing hours, and zero heating.

### How to run

In Developer Tools → Actions:

```yaml
action: tado.x_scan_vaillant_hourly_quality
data:
  days: 120
  tolerance_wh: 1
  confirmation_days: 3
```

**Interpretation caveat:** Uniform positive hourly values are strong evidence of interpolation, not proof. A nonuniform profile is *not by itself* proof of authentic measured hourly gas use. Review the transition before selecting a cutoff. No cutoff/deletion is automated by this release.

The existing historical v2 reconciliation and the original myPyllant data remain otherwise unchanged.
