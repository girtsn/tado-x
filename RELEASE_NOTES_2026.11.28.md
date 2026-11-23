# tado X 2026.11.28 — Heating-gas reconciliation and calendar fixes

- Recent heating-history selections (up to 92 days) are recalculated **read-only** from current myPyllant hourly heating-gas data and tado room-demand statistics. This prevents delayed or revised Vaillant figures from leaving dashboard estimates permanently understated.
- Dashboard now shows current Vaillant heating input and the difference from historical v2 allocations, with warnings for incomplete input hours.
- New Developer Tools action: `tado.x_reconcile_heating_allocation`. Optional `date: "2026-11-22"` checks a precise Home Assistant calendar day and reports the current source-versus-archived hourly differences. It **never writes statistics**.
- Removed the misleading dashboard "Update estimates" write action; Refresh now reads live source data.
- Date picker uses the **Home Assistant configured timezone**, irrespective of phone/browser timezone. Includes DST-correct 23/25-hour days and straightforward single-day selection.
- Added regression tests for historical source revisions and DST boundaries.

**Data preservation:** This release does not change original myPyllant statistics or overwrite archived tado v2 records. Selections longer than 92 days continue to use existing archived v2 data and may contain historic underestimates. The read-only reconciliation service can identify those discrepancies for a given day.
