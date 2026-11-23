# Tado X 2026.11.30.1 — Household-scoped historical allocation cutoff

**Purpose:** For a household whose pre-3-November Vaillant hourly Gas Heating statistics are flat positive daily totals divided into hours, allow a fully controlled one-time removal of only the **derived Tado room gas allocation distributions** from earlier dates.

- New action: `tado.x_apply_heating_allocation_cutoff`, with safe preview (`dry_run: true`) and explicit deletion confirmation (`dry_run: false`, `confirm_delete_pre_cutoff: true`).
- Before any modification, fully reconstruct all complete post-cutoff hours from original Vaillant hourly heating gas and Tado hourly room demand, and abort if source coverage is incomplete.
- Use **Home Assistant's supported ranged Recorder clear** to delete only pre-cutoff hourly and aggregated rows for the **10 derived Tado v2 room gas series plus the derived Unallocated series**.
- Preserve original Vaillant Gas Heating and hot-water data, underlying Tado heating demand, room temperatures, and unrelated HA statistics.
- Rebuild every retained hourly v2 state and cumulative sum starting at zero and wait for import completion; verify the first and last committed rows of every derived series.
- Persist the cutoff separately per household; never impose a global cutoff on other Tado X users.
- Respect the cutoff in automatic/manual reconciliation, dashboard history, and Unallocated diagnostics, so old synthetic distributions cannot be recreated.
- On interrupted or failed migration, suspend subsequent automatic allocation writes until the confirmed action is retried.
- Unit tests cover read-only preview, explicit approval requirement, exact targeted IDs/range, rebuilt sums, missing-source guard, and historical clipping.

### Before upgrading/acting
Make a **Home Assistant full backup**. Installing this release is non-destructive: no data is deleted until the explicitly confirmed action is executed.

### How to apply to the household previously diagnosed
First preview in Developer Tools → Actions:

```yaml
action: tado.x_apply_heating_allocation_cutoff
data:
  date: "2026-11-03"
  dry_run: true
```

Then apply when the preview is clean and the backup exists:

```yaml
action: tado.x_apply_heating_allocation_cutoff
data:
  date: "2026-11-03"
  dry_run: false
  confirm_delete_pre_cutoff: true
```

**No adjustment to Vaillant's daily/hourly ~0.47% discrepancy** is attempted: allocation continues to reflect available Vaillant hourly energy, without inventing readings.

**Safety note:** the cutoff date represents the first day judged to contain non-synthetic hourly data, not absolute proof that its measurements are independently metered.