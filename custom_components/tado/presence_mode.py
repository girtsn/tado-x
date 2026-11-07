"""Read-only Tado household presence semantics.

Tado X reports two different values in its normal home-state poll:
* presenceLocked: whether the household mode is manually controlled.
* presence: the actual HOME/AWAY state, even while Auto is selected.

Keep these separate so a 'Home' effective state under Auto never appears
as a manual override. Missing/invalid API values must remain unknown.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def effective_presence(geofence: Mapping[str, Any] | None) -> str | None:
    """Return observed Home/Away, or None when the API has no valid value."""
    if not isinstance(geofence, Mapping):
        return None
    value = geofence.get("presence")
    if not isinstance(value, str):
        return None
    return {"HOME": "Home", "AWAY": "Away"}.get(value.upper())


def selected_presence_mode(geofence: Mapping[str, Any] | None) -> str | None:
    """Return the configured manual Home/Away or Auto control mode."""
    if not isinstance(geofence, Mapping):
        return None
    locked = geofence.get("presenceLocked")
    if locked is False:
        return "Auto"
    if locked is True:
        return effective_presence(geofence)
    return None
