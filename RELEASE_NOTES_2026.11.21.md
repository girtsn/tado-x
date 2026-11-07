# tado X v2026.11.21 — reliable frontend loading

Stable HACS update with no heating control, API polling, or private automation changes.

- The managed Heating panel custom element registers **without waiting** for dependent JavaScript modules. This avoids an intermittent blank sidebar during frontend reloads.
- If a dependent frontend module fails or is temporarily unavailable, the panel displays a visible diagnostic message and a **Retry loading** button.
- Versioned dependencies preserve cache invalidation, but panel reload on an installed version change is now guarded by session storage to avoid repeated browser reload loops.
- No changes to the already working Renson Sense integration, existing tado entities, heating controls, schedules, API health sensors or notification automations.

After upgrading through HACS, restart Home Assistant and reopen the Heating panel.
