# tado X v2026.11.23 — Mobile navigation and sidebar capitalization

- Restore access to Home Assistant navigation on phones and narrow windows: the integration-managed Heating dashboard now displays an accessible hamburger menu that opens Home Assistant's native sidebar.
- Show **Tado X Heating** rather than **tado X Heating** in the Home Assistant sidebar.
- Preserve the existing self-updating managed frontend loader, Heating Overview and Schedules tabs, current entities and heating controls.
- The version bump loads the corrected panel asset under a new per-release URL. No dashboard YAML changes are required.

**Installation:** Update the custom repository in HACS and restart Home Assistant. In the mobile Companion App, reopen Heating and use the new menu button in the top-left of the panel.
