# Tado X v2026.11.32 — Respect Home Assistant timezone preference

- Date selectors now honor **Home Assistant user profile → Time zone**:
  - **Use local time zone:** View calendar dates in the viewing device's actual time zone.
  - **Use server time zone:** View calendar dates in the Home Assistant server's configured time zone.
- The setting is evaluated at the time the picker is shown, instead of forcing the server time zone. Selected civil dates are preserved when switching preferences in a loaded picker.
- Correct 23/25-hour daylight-saving day lengths, current-week start-day preference, one-tap single-day selection, and inclusive calendar-date selection are retained.
- Initial date ranges are computed with the loaded Home Assistant profile, not provisional browser-only dates.
- Automated tests cover a Brussels home viewed from Riga, profile switching, both DST transitions, and regression of existing picker behavior.
- Heating-gas room history now also sends the profile-selected IANA timezone to the backend for correct day/month grouping; the physical Brussels gas-allocation cutoff and Recorder data remain unchanged.
- No historical Home Assistant Recorder entries, device controls, temperature data, Vaillant statistics, or Tado room allocations are modified by this update.
