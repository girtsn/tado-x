# tado X 2026.11.26

## Fixed
- The dashboard date selector now follows **Home Assistant → User profile → First day of the week**, instead of always relying on the browser's locale.
- Both **This week** history ranges and the calendar's weekday columns respect the profile preference. **Automatic** follows Home Assistant's selected language.
- Changing the Home Assistant week-start preference updates open date selectors without altering stored measurements.
- The tado X weekly heating schedule editor follows the user-selected first weekday visually, without changing tado's API weekday mapping.
- Standalone heating/history cards also initialize their weekly period from the Home Assistant preference.

## Verification
- Offline regression coverage added for Monday/Sunday/Saturday, automatic en-GB/en-US week starts, and user preference changes. Device schedules and historical recordings are not rewritten.
