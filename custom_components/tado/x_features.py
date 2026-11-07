"""Opt-in features for a shared/public tado integration.

Core tado entities are always supported. Advanced tado X controls and the
household-specific radiator + myPyllant model are separate per-home options.

No home IDs, addresses, email addresses or account identifiers appear here.
Only preexisting Recorder statistics for THIS tado home can activate the
legacy household-energy option on upgrade; new installations default off.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging

from .const import (
    CONF_X_ADVANCED, CONF_X_HOME_ENERGY, CONF_X_LEGACY_ENERGY_PROBE,
)

_LOGGER = logging.getLogger(__name__)


def advanced_enabled(entry) -> bool:
    return entry.options.get(CONF_X_ADVANCED) is True


def energy_enabled(entry) -> bool:
    return entry.options.get(CONF_X_HOME_ENERGY) is True


async def restore_used_legacy_energy_option(hass, entry, coordinator) -> bool:
    """Enable household energy only if it has v2 allocated statistics already.

    Called only once for existing v2 entries after the tado home ID is
    available. An API/Recorder error keeps the probe pending so a future
    restart can retry, without enabling extras for anyone.
    """
    if not entry.options.get(CONF_X_LEGACY_ENERGY_PROBE):
        return energy_enabled(entry)
    if energy_enabled(entry):
        opts = {**entry.options, CONF_X_LEGACY_ENERGY_PROBE: False}
        hass.config_entries.async_update_entry(entry, options=opts)
        return True
    if not coordinator.is_x:
        opts = {**entry.options, CONF_X_LEGACY_ENERGY_PROBE: False}
        hass.config_entries.async_update_entry(entry, options=opts)
        return False

    try:
        from .heat_allocation import _fetch, _stat_id
        ids = {_stat_id(coordinator, zone["id"]) for zone in coordinator.zones}
        if not ids:
            raise ValueError("No tado X rooms loaded")
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=90)
        snapshots = await _fetch(
            hass, start, end, ids, period="day"
        )
        previously_used = any(snapshots.get(stat_id) for stat_id in ids)
    except Exception as err:
        _LOGGER.warning(
            "Could not check previous household energy statistics; "
            "energy extras remain disabled and can be enabled manually in "
            "tado integration options, or checked again after restart: %s",
            err,
        )
        return False

    opts = {
        **entry.options,
        CONF_X_HOME_ENERGY: previously_used,
        CONF_X_LEGACY_ENERGY_PROBE: False,
    }
    hass.config_entries.async_update_entry(entry, options=opts)
    if previously_used:
        _LOGGER.info(
            "Preserved previously used tado X household energy features "
            "based on existing Recorder estimates"
        )
    return previously_used
