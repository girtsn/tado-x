# tado X v2026.11.20 — privacy cleanup

Stable HACS update.

- Remove the household-specific device availability email automation from the public integration distribution. Private Home Assistant automations and dashboards should be maintained separately, not in a reusable HACS integration.
- Retain the existing integration-managed Heating panel, generic dashboard example, public diagnostic entities and API health monitoring exactly as before.
- Update regression tests so the public integration no longer depends on the personal `notify.email_girts` automation.

**Existing Home Assistant automations are not modified by HACS.** The private configuration should be maintained independently and manually installed into Home Assistant.

Note: removal from the default branch and new HACS release does **not** erase copies in older public Git commits, tags, PR diffs, or downloads. Full historical deletion requires a separate Git history rewrite and tag/release management.
