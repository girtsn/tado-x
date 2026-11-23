# tado X 2026.11.29 — Repair archived heating-gas allocation (v2)

**Main improvement:** Previously published room allocations are now reconciled against the current Vaillant hourly heating-gas statistics. This repairs the archived ~21.25 kWh allocation for 22 November when Vaillant's corresponding hourly profile later reports ~46.53 kWh (actual values depend on Recorder data at the time of repair).

- Keep the **existing v2 statistic IDs** and repair their hourly `state` and cumulative `sum` through Home Assistant's supported external-statistics upsert operation. No separate v3 IDs, direct SQL, or destructive Recorder edits.
- The same weighting function (hourly tado demand × installed EN442 radiator capacity) is used in live views and persisted allocations.
- On the first hourly job after each integration restart, review up to **35 days** of archived room allocations, then reconcile the latest **3 days** at HH:15 to catch late Vaillant updates.
- For an explicit preview, invoke `tado.x_compute_heating_allocation` with `days: 35, dry_run: true`. Use `dry_run: false` to queue corrections. Both return `changed_hours`, `changed_statistic_rows`, reconstructed totals and source coverage. Do not expect an immediate recorder write to be fully visible until queued writes have been processed.
- **Safety:** Any missing Vaillant source hour with later published allocations blocks the whole rewrite; no partial rebasing across unknown input. Missing unpublished trailing source hours are deferred.
- Vaillant's source statistics and original myPyllant component are **not** changed.
- Added regression tests for late source corrections, cumulative-sum rebasing, idempotence, dry-run safety and missing-source protection.
- The existing read-only dashboard and per-day diagnostic remain available for checking results.

**Remaining ~0.5% difference:** The Vaillant Energy dashboard's daily heating total and the underlying hourly profile are not identical for 22 November (approximately 46.748 vs 46.530 kWh). This release does not guess or scale away that difference; it allocates the exact hourly input available in Recorder, with all source hours covered, pending a separate investigation of Vaillant's aggregation.

**After updating:** Restart Home Assistant, then use `tado.x_reconcile_heating_allocation` with `date: "2026-11-22"` after the hourly reconciliation job has completed. The `legacy_difference_kwh` should fall near zero once updated v2 rows are imported and visible. If `status: blocked_missing_published_source_hour` is returned, no historical writes were attempted.
