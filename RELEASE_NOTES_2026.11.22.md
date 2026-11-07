# tado X 2026.11.22 — aligned self-updating dashboard

- A stable sidebar loader checks the integration's version without caching and imports a per-release managed Heating panel, avoiding normal full-page browser reloads on subsequent HACS upgrades.
- Dashboard and dependency assets now use version-specific URL paths and release-specific custom-element names, so an open browser tab cannot accidentally reuse older card classes.
- The existing fixed Lovelace custom-card names and URLs remain supported for user-created dashboards.
- Existing retryable dependency loading, date-range picker, schedule editing, temperature/energy history and heating controls are preserved.
- Active heating actions and unsaved schedule edits prevent automatic replacement of the open dashboard.
- If Home Assistant is restarting or an asset is temporarily unavailable, the previous dashboard stays visible and the loader retries on focus/visibility and every minute.
- The release pipeline now derives the new release tag from the manifest, with a guard against stale workflow runs.

**One-time transition:** The previously cached direct panel does not have the loader. After updating HACS and restarting Home Assistant, close/reopen the tab; one final hard refresh may be needed to obtain the new panel registration. Once active, subsequent updates should not require Ctrl+F5 unless an external cache overrides the frontend's no-cache requests.
