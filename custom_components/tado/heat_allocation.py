"""Estimated heating-gas allocation to tado rooms using existing HA Recorder.

Input energy: myPyllant's ORIGINAL hourly gas HEATING external statistic (Wh).
Input activity: Recorder hourly mean of each tado room's heating demand (%).
Output: NEW, separate tado: external statistics (kWh of attributed gas input).

This is NOT radiator thermal output, not measured valve travel and not actual
individual radiator energy. No Vaillant recorder/statistic/source is modified.
"""

from __future__ import annotations

from datetime import date as calendar_date, datetime, timedelta, timezone
import asyncio
import logging
from zoneinfo import ZoneInfo
from typing import Any

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import (
    StatisticData, StatisticMetaData, StatisticMeanType,
    async_add_external_statistics, statistics_during_period,
)
from homeassistant.helpers import entity_registry as er
from homeassistant.exceptions import HomeAssistantError

from .radiator_inventory import radiator_capacity_report, require_valid_capacities

_LOGGER = logging.getLogger(__name__)
PREFIX = "tado:x_radiator_weighted_gas_heating_v2_"
GAS_PROFILE = ("CONSUMED_PRIMARY_ENERGY", "HEATING")
KWH_PER_WH = 0.001
MAX_BACKFILL_DAYS = 35
CUTOFF_OPTION = "x_gas_allocation_cutoff_utc"
CUTOFF_COMPLETE_OPTION = "x_gas_allocation_cutoff_applied"


def _stat_id(main, zone_id: int | str) -> str:
    return f"{PREFIX}{main.home_id}_{zone_id}"


def _allocation_cutoff(main) -> datetime | None:
    """Return per-household UTC cutoff or None (never a global cutoff)."""
    value = main.config_entry.options.get(CUTOFF_OPTION)
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as err:
        raise HomeAssistantError("Invalid saved heating allocation cutoff") from err
    if stamp.tzinfo is None:
        raise HomeAssistantError("Saved heating allocation cutoff requires UTC offset")
    return stamp.astimezone(timezone.utc)


def _cutoff_pending(main) -> bool:
    return bool(_allocation_cutoff(main)) and not main.config_entry.options.get(
        CUTOFF_COMPLETE_OPTION, False
    )




def _capacities(main) -> dict[str, float]:
    """Actual installed radiator EN442 W, grouped per named tado room.

    Never silently fall back to 1kW if a room is unknown or a multi-radiator
    count disagrees with the physical inventory. An existing manual setting
    wins over an inferred/nominal inventory value.
    """
    return require_valid_capacities(
        main.zones, main.config_entry.options.get("x_capacity_kw", {}),
        main.config_entry.options.get("x_radiator_room_mapping", {})
    )


def _gas_statistic(hass) -> str | None:
    """Use the stable ID exported by the running myPyllant hourly manager."""
    matches = set()
    for data in (hass.data.get("mypyllant") or {}).values():
        if not isinstance(data, dict):
            continue
        manager = data.get("hourly_statistics_manager")
        if manager is None:
            continue
        try:
            stat = manager.profile_statistics().get(GAS_PROFILE)
        except (ValueError, KeyError, AttributeError):
            continue
        if stat:
            matches.add(stat)
    return next(iter(matches)) if len(matches) == 1 else None


def _room_sensor_ids(hass, main) -> dict[str, str]:
    registry = er.async_get(hass)
    mapped = {}
    for zone in main.zones:
        zid = str(zone["id"])
        unique_id = f"heating {zid} {main.home_id}"
        entity = registry.async_get_entity_id("sensor", "tado", unique_id)
        if entity:
            mapped[zid] = entity
    return mapped


def _hour(t: float) -> datetime:
    return datetime.fromtimestamp(t, tz=timezone.utc)


async def _fetch(hass, start, end, ids: set[str], period: str = "hour"):
    return await get_instance(hass).async_add_executor_job(
        statistics_during_period, hass, start, end, ids,
        period, None, {"sum", "mean"},
    )


def _rows_by_start(rows) -> dict[float, dict]:
    return {float(r["start"]): r for r in (rows or []) if r.get("start") is not None}


def _meta(main, zone_id: str, name: str):
    return StatisticMetaData(
        mean_type=StatisticMeanType.NONE, has_sum=True,
        name=f"Estimated allocated heating gas: {name}",
        source="tado", statistic_id=_stat_id(main, zone_id),
        unit_class="energy", unit_of_measurement="kWh",
    )


def _calculate_hourly_shares(
    gas_kwh: float, means: dict[str, float | None],
    capacities: dict[str, float],
) -> tuple[dict[str, float], float]:
    """Single allocation formula used for both live history and persisted v2."""
    if any(value is None or not 0 <= value <= 100 for value in means.values()):
        return {zid: 0.0 for zid in means}, gas_kwh
    weights = {zid: float(value) * capacities[zid] for zid, value in means.items()}
    total_weight = sum(weights.values())
    if total_weight <= 0:
        return {zid: 0.0 for zid in means}, gas_kwh
    return {
        zid: gas_kwh * weight / total_weight for zid, weight in weights.items()
    }, 0.0


async def allocate_recent(hass, main, *, days: int = 3, dry_run: bool = False) -> dict:
    """Reconcile archived v2 hourly rows against CURRENT Vaillant gas statistics.

    Home Assistant's supported external-statistics importer performs an upsert:
    existing hourly records are updated. Recalculate state AND cumulative sum,
    including all following hours within the rebuilt window, so late Vaillant
    corrections never leave past gas shares or cumulative totals inconsistent.

    Never read or write a different household or the original Vaillant series.
    If a historical source hour is absent, refuse any rewrite that might shift
    the cumulative sums across that gap. A missing UNPUBLISHED trailing hour
    is safe: defer it until the next scheduled run.
    """
    if not 1 <= days <= MAX_BACKFILL_DAYS:
        raise HomeAssistantError("Reconciliation days must be between 1 and 35")
    if not getattr(main, "is_x", False):
        raise HomeAssistantError("Heating allocation requires tado X")
    if _cutoff_pending(main):
        return {
            "status": "allocation_cutoff_cleanup_pending",
            "no_statistics_modified": True,
            "message": "Finish/retry the explicit confirmed cutoff cleanup before "
                       "automatic allocation publishes further statistics.",
        }
    source_id = _gas_statistic(hass)
    if source_id is None:
        return {
            "status": "no_unique_vaillant_gas_heating_statistic",
            "no_statistics_modified": True,
        }
    room_sensors = _room_sensor_ids(hass, main)
    if len(room_sensors) != len(main.zones):
        return {
            "status": "room_heating_sensors_not_ready",
            "rooms_found": len(room_sensors), "rooms_expected": len(main.zones),
            "no_statistics_modified": True,
        }
    try:
        cap = _capacities(main)
    except HomeAssistantError as err:
        report = radiator_capacity_report(
            main.zones, main.config_entry.options.get("x_capacity_kw", {}),
            main.config_entry.options.get("x_radiator_room_mapping", {}),
        )
        return {
            "status": "radiator_capacity_mapping_needs_review",
            "message": str(err), "rooms": report["rooms"],
            "no_statistics_modified": True,
        }

    end = datetime.now(timezone.utc).replace(
        minute=0, second=0, microsecond=0
    )
    cutoff = _allocation_cutoff(main)
    requested_start = max(end - timedelta(days=days), cutoff) if cutoff else (
        end - timedelta(days=days)
    )
    if requested_start >= end:
        return {
            "status": "no_hours_after_cutoff",
            "no_statistics_modified": True,
            "hours": 0,
        }
    zone_ids = (*room_sensors, "unallocated")
    out_ids = {_stat_id(main, zid) for zid in zone_ids}
    snapshots = await _fetch(
        hass, requested_start - timedelta(hours=1), end,
        {source_id, *room_sensors.values(), *out_ids},
    )
    source = _rows_by_start(snapshots.get(source_id))
    rooms = {
        zid: _rows_by_start(snapshots.get(entity_id))
        for zid, entity_id in room_sensors.items()
    }
    outputs = {
        zid: _rows_by_start(snapshots.get(_stat_id(main, zid)))
        for zid in zone_ids
    }

    # The feature was introduced recently. Do not invent heating allocations
    # preceding the earliest already published v2 statistic within the window.
    published = sorted({
        stamp for series in outputs.values()
        for stamp in series
        if requested_start.timestamp() <= stamp < end.timestamp()
    })
    valid_source = sorted(
        stamp for stamp, row in source.items()
        if stamp >= requested_start.timestamp()
        and stamp < end.timestamp()
        and source.get(stamp - 3600) is not None
        and row.get("sum") is not None
        and source[stamp - 3600].get("sum") is not None
    )
    if not valid_source:
        return {"status": "no_valid_source_hours",
                "hours": 0, "no_statistics_modified": True}
    # With an applied cutoff the rebuilt archive begins exactly at that hour,
    # even if the first old v2 row appears later than the source hour.
    start_ts = (
        requested_start.timestamp() if cutoff is not None else
        max(requested_start.timestamp(), published[0] if published else valid_source[0])
    )
    start = _hour(start_ts)
    if start >= end:
        return {"status": "no_hours_to_reconcile", "hours": 0,
                "no_statistics_modified": True}

    # Read a prior baseline independent of the latest stored cumulative sum:
    # the latter already contains the hours we are about to recalculate.
    previous = await _fetch(
        hass, start - timedelta(days=35), start, out_ids
    )
    baseline = {}
    for zid in zone_ids:
        older = [
            r for r in previous.get(_stat_id(main, zid), [])
            if r.get("sum") is not None and float(r["start"]) < start_ts
        ]
        baseline[zid] = float(max(older, key=lambda r: r["start"])["sum"]) \
            if older else 0.0
    if cutoff is not None and start == cutoff:
        # The first post-cutoff statistic deliberately begins at zero, not
        # an old synthetic cumulative baseline.
        baseline = {zid: 0.0 for zid in zone_ids}
    running = baseline.copy()
    pending: dict[str, list[StatisticData]] = {zid: [] for zid in zone_ids}
    changed_hours: set[float] = set()
    missing_hours: list[str] = []
    gas_total = unknown_total = 0.0
    first_missing: float | None = None
    calculated = 0

    for offset in range(int((end - start).total_seconds() // 3600)):
        at = start + timedelta(hours=offset)
        stamp = at.timestamp()
        prior = stamp - 3600
        current, prev = source.get(stamp), source.get(prior)
        if current is None or prev is None or (
            current.get("sum") is None or prev.get("sum") is None
        ):
            first_missing = stamp
        else:
            delta_wh = float(current["sum"]) - float(prev["sum"])
            if not 0 <= delta_wh <= 200000:
                first_missing = stamp
        if first_missing is not None:
            missing_hours.append(at.isoformat())
            break

        gas_kwh = delta_wh * KWH_PER_WH
        means = {
            zid: (data[stamp].get("mean") if stamp in data else None)
            for zid, data in rooms.items()
        }
        shares, unknown = _calculate_hourly_shares(gas_kwh, means, cap)
        values = {**shares, "unallocated": unknown}
        calculated += 1
        gas_total += gas_kwh
        unknown_total += unknown
        for zid in zone_ids:
            value = values[zid]
            running[zid] += value
            old = outputs[zid].get(stamp)
            differs = (
                old is None or old.get("sum") is None
                or abs(float(old["sum"]) - running[zid]) > 0.000001
                or old.get("state") is None
                or abs(float(old["state"]) - value) > 0.000001
            )
            if differs:
                pending[zid].append(StatisticData(
                    start=at, state=value, sum=running[zid],
                ))
                changed_hours.add(stamp)

    # A missing source hour before an already-published later v2 row would
    # invalidate the cumulative baseline of those later records. Do not write
    # any corrections until the missing Vaillant source hour reappears.
    if first_missing is not None and any(
        stamp >= first_missing for data in outputs.values() for stamp in data
    ):
        return {
            "status": "blocked_missing_published_source_hour",
            "hours": calculated,
            "first_missing_utc": _hour(first_missing).isoformat(),
            "no_statistics_modified": True,
            "message": "Cannot safely rebase existing cumulative v2 rows across "
                       "a missing Vaillant source hour.",
        }

    changed_rows = sum(len(rows) for rows in pending.values())
    if not dry_run:
        names = {str(z["id"]): str(z.get("name", z["id"])) for z in main.zones}
        names["unallocated"] = "Unallocated / no room demand"
        for zid, rows in pending.items():
            if rows:
                async_add_external_statistics(
                    hass, _meta(main, zid, names[zid]), rows
                )
    return {
        "status": (
            "dry_run" if dry_run else
            "reconciled_hours_queued" if changed_rows else "already_reconciled"
        ),
        "hours": calculated,
        "start_time": start.isoformat(),
        "end_time": (start + timedelta(hours=calculated)).isoformat(),
        "first_missing_utc": missing_hours[0] if missing_hours else None,
        "changed_hours": len(changed_hours),
        "changed_statistic_rows": changed_rows,
        "gas_heating_kwh": round(gas_total, 3),
        "allocated_kwh": round(gas_total - unknown_total, 3),
        "unallocated_kwh": round(unknown_total, 3),
        "no_statistics_modified": dry_run or changed_rows == 0,
        "source": "Current myPyllant hourly Gas Heating + tado room demand",
        "capacity_basis": "EN442 75/65/20 radiator output",
        "interpretation": "Derived gas input shares, not delivered radiator heat",
        "note": "Uses supported Recorder external-statistics upsert; "
                "existing v2 IDs stay stable and Vaillant input is unchanged.",
    }


async def configure_heating_allocation_cutoff(
    hass, main, *, date: str, dry_run: bool = True,
    confirm_delete_pre_cutoff: bool = False,
) -> dict:
    """Preview or execute one-household Tado-only pre-cutoff data cleanup.

    Retained hourly rows are prepared and validated *before* deletion.
    A persistent per-entry cutoff then blocks accidental old-hour recreation.
    Use only Home Assistant's supported Recorder ranged clear/import APIs.
    Nothing accesses or changes the myPyllant source statistic.
    """
    if not getattr(main, "is_x", False):
        raise HomeAssistantError("Heating allocation cutoff requires tado X")
    try:
        day = calendar_date.fromisoformat(date)
    except (TypeError, ValueError) as err:
        raise HomeAssistantError("Cutoff date must be YYYY-MM-DD") from err
    zone = ZoneInfo(hass.config.time_zone or "UTC")
    cutoff = datetime(
        day.year, day.month, day.day, tzinfo=zone
    ).astimezone(timezone.utc)
    end = datetime.now(timezone.utc).replace(
        minute=0, second=0, microsecond=0
    )
    if cutoff >= end:
        raise HomeAssistantError("Cutoff must precede the current completed hour")
    if end - cutoff > timedelta(days=365):
        raise HomeAssistantError("Cutoff cleanup is limited to the last 365 days")

    configured = _allocation_cutoff(main)
    if configured is not None and configured != cutoff:
        raise HomeAssistantError(
            "A different allocation cutoff is already configured. "
            "Changing it would require a separate migration."
        )
    source_id = _gas_statistic(hass)
    if source_id is None:
        return {"status": "no_unique_vaillant_gas_heating_statistic",
                "no_statistics_modified": True}
    room_sensors = _room_sensor_ids(hass, main)
    if len(room_sensors) != len(main.zones):
        return {"status": "room_heating_sensors_not_ready",
                "no_statistics_modified": True}
    capacities = _capacities(main)
    zone_ids = (*room_sensors, "unallocated")
    stat_ids = {_stat_id(main, zid) for zid in zone_ids}

    snapshots = await _fetch(
        hass, cutoff - timedelta(hours=1), end,
        {source_id, *room_sensors.values()}, "hour"
    )
    source = _rows_by_start(snapshots.get(source_id))
    demands = {
        zid: _rows_by_start(snapshots.get(entity_id))
        for zid, entity_id in room_sensors.items()
    }
    running = {zid: 0.0 for zid in zone_ids}
    rows: dict[str, list[StatisticData]] = {zid: [] for zid in zone_ids}
    unknown_hours = 0
    invalid_hours = []
    for offset in range(int((end - cutoff).total_seconds() // 3600)):
        hour = cutoff + timedelta(hours=offset)
        stamp = hour.timestamp()
        current, previous = source.get(stamp), source.get(stamp - 3600)
        if (
            current is None or previous is None
            or current.get("sum") is None or previous.get("sum") is None
        ):
            invalid_hours.append(hour.isoformat())
            continue
        delta_wh = float(current["sum"]) - float(previous["sum"])
        if not 0 <= delta_wh <= 200000:
            invalid_hours.append(hour.isoformat())
            continue
        gas_kwh = delta_wh * KWH_PER_WH
        means = {}
        for zid, samples in demands.items():
            val = samples.get(stamp, {}).get("mean")
            try:
                means[zid] = float(val) if val is not None else None
            except (TypeError, ValueError):
                means[zid] = None
        allocations, unallocated = _calculate_hourly_shares(
            gas_kwh, means, capacities
        )
        if unallocated > 0:
            unknown_hours += 1
        values = {**allocations, "unallocated": unallocated}
        for zid in zone_ids:
            value = values[zid]
            running[zid] += value
            rows[zid].append(StatisticData(
                start=hour, state=value, sum=running[zid],
            ))

    if invalid_hours:
        return {
            "status": "blocked_missing_or_invalid_vaillant_hours",
            "read_only": True,
            "no_statistics_modified": True,
            "cutoff_local_date": date,
            "first_invalid_hours_utc": invalid_hours[:10],
            "invalid_hour_count": len(invalid_hours),
            "message": "No records were deleted. A continuous Vaillant source "
                       "is required for safe rebasing of cumulative statistics.",
        }

    retained_hours = len(next(iter(rows.values())))
    if not retained_hours:
        raise HomeAssistantError("No completed source hours after the cutoff")

    # Count only the targeted tado outputs. Never read data from other
    # households for cleanup or supply a wildcard statistic ID to Recorder.
    older = await _fetch(
        hass, cutoff - timedelta(days=365), cutoff, stat_ids, "hour"
    )
    old_rows = sum(
        len([r for r in older.get(stat_id, [])
             if float(r["start"]) < cutoff.timestamp()])
        for stat_id in stat_ids
    )
    result = {
        "status": "cutoff_preview" if dry_run else "cutoff_applied",
        "cutoff_local_date": date,
        "cutoff_utc": cutoff.isoformat(),
        "timezone": str(zone),
        "read_only": dry_run,
        "no_vaillant_or_tado_demand_statistics_modified": True,
        "old_tado_hourly_rows_to_remove": old_rows,
        "target_statistic_ids": sorted(stat_ids),
        "target_statistic_count": len(stat_ids),
        "retained_hours_per_statistic": retained_hours,
        "retained_statistic_rows_to_rebuild": sum(map(len, rows.values())),
        "retained_heating_gas_kwh": round(sum(running.values()), 3),
        "retained_allocated_kwh": round(
            sum(v for k, v in running.items() if k != "unallocated"), 3
        ),
        "retained_unallocated_kwh": round(running["unallocated"], 3),
        "retained_unallocated_hours": unknown_hours,
        "note": "Deletes only pre-cutoff hourly/daily v2 tado room statistics; "
                "Vaillant gas and tado room-demand inputs are untouched.",
    }
    if dry_run:
        return {**result, "no_statistics_modified": True}
    if not confirm_delete_pre_cutoff:
        raise HomeAssistantError(
            "Cleanup requires confirm_delete_pre_cutoff=true and "
            "dry_run=false after a Home Assistant backup."
        )

    # Mark the specific household as pending before deleting. An interrupted
    # migration cannot silently resume the pre-cutoff hourly publisher.
    entry = main.config_entry
    pending_options = {
        **entry.options,
        CUTOFF_OPTION: cutoff.isoformat(),
        CUTOFF_COMPLETE_OPTION: False,
    }
    hass.config_entries.async_update_entry(entry, options=pending_options)
    instance = get_instance(hass)
    completed = asyncio.Event()
    def done() -> None:
        hass.loop.call_soon_threadsafe(completed.set)
    instance.async_clear_statistics(
        sorted(stat_ids),
        start_time=datetime(1970, 1, 1, tzinfo=timezone.utc),
        end_time=cutoff,
        on_done=done,
    )
    await asyncio.wait_for(completed.wait(), timeout=120)

    names = {
        str(z["id"]): str(z.get("name", z["id"])) for z in main.zones
    }
    names["unallocated"] = "Unallocated / no room demand"
    for zid in zone_ids:
        async_add_external_statistics(
            hass, _meta(main, zid, names[zid]), rows[zid]
        )
    await asyncio.wait_for(instance.async_block_till_done(), timeout=120)

    # The imported series must have a zero-based cumulative starting point.
    # Only mark completed when all exact final hourly sums are readable.
    saved = await _fetch(hass, cutoff, end, stat_ids, "hour")
    for zid in zone_ids:
        actual = _rows_by_start(saved.get(_stat_id(main, zid)))
        first = rows[zid][0]
        last = rows[zid][-1]
        for expected in (first, last):
            found = actual.get(expected["start"].timestamp())
            if found is None or found.get("sum") is None or abs(
                float(found["sum"]) - float(expected["sum"])
            ) > 0.00001:
                return {
                    **result,
                    "status": "cutoff_rebuild_unverified_retry_required",
                    "read_only": False,
                    "migration_pending": True,
                    "no_statistics_modified": False,
                    "message": "The pre-cutoff tado rows were cleared, but "
                               "the retained rebuild could not be verified. "
                               "Run the same action again; automatic hourly "
                               "allocation remains suspended.",
                }

    hass.config_entries.async_update_entry(
        entry, options={
            **entry.options,
            CUTOFF_OPTION: cutoff.isoformat(),
            CUTOFF_COMPLETE_OPTION: True,
        }
    )
    main.x_allocation_full_rebuild_pending = False
    return {**result, "no_statistics_modified": False,
            "migration_pending": False}




async def _live_reconciled_history(
    hass, main, start: datetime, end: datetime, period: str,
    group: str, tz: ZoneInfo,
) -> dict | None:
    """Recompute display estimates from CURRENT hourly Recorder inputs.

    Previously published v2 room statistics can be permanently stale if
    myPyllant revises hourly gas statistics after the append-only publication.
    Never edit or rebase those statistics here. Prefer a read-only reconstruction
    for bounded date ranges, retaining the archived data for longer views.
    """
    if end - start > timedelta(days=92):
        return None
    source_id = _gas_statistic(hass)
    if source_id is None:
        return None
    room_sensors = _room_sensor_ids(hass, main)
    if len(room_sensors) != len(main.zones):
        return None
    try:
        capacities = _capacities(main)
    except HomeAssistantError:
        return None

    names = {str(z["id"]): str(z.get("name", z["id"])) for z in main.zones}
    names["unallocated"] = "Unallocated"
    ids = {source_id} | set(room_sensors.values()) | {
        _stat_id(main, zone_id) for zone_id in names
    }
    data = await _fetch(
        hass, start - timedelta(hours=1), end, ids, "hour"
    )
    source = _rows_by_start(data.get(source_id))
    demands = {
        zid: _rows_by_start(data.get(sensor_id))
        for zid, sensor_id in room_sensors.items()
    }
    stored = {
        zid: _rows_by_start(data.get(_stat_id(main, zid)))
        for zid in names
    }
    timeline: dict[str, dict[str, float]] = {}
    hourly: list[dict[str, Any]] = []
    input_total = stored_total = unknown_total = 0.0
    valid_hours = missing_hours = stale_hours = 0
    hour = start
    while hour < end:
        t = hour.timestamp()
        prev_t = (hour - timedelta(hours=1)).timestamp()
        current, previous = source.get(t), source.get(prev_t)
        if (
            current is None or previous is None
            or current.get("sum") is None or previous.get("sum") is None
        ):
            missing_hours += 1
            hour += timedelta(hours=1)
            continue
        delta_wh = float(current["sum"]) - float(previous["sum"])
        if not 0 <= delta_wh <= 200000:
            missing_hours += 1
            hour += timedelta(hours=1)
            continue
        gas_kwh = delta_wh * KWH_PER_WH
        valid_hours += 1
        input_total += gas_kwh

        measurements = {}
        for zid, samples in demands.items():
            sample = samples.get(t)
            raw = sample.get("mean") if sample is not None else None
            try:
                measurements[zid] = float(raw) if raw is not None else None
            except (ValueError, TypeError):
                measurements[zid] = None
        values, unknown = _calculate_hourly_shares(
            gas_kwh, measurements, capacities
        )
        unknown_total += unknown
        values["unallocated"] = unknown

        local = hour.astimezone(tz)
        key = (
            local.strftime("%Y-%m") if group == "month" else
            local.strftime("%Y-%m-%d") if group == "day" else
            local.strftime("%Y-%m-%dT%H:00")
        )
        slot = timeline.setdefault(key, {})
        for zid, amount in values.items():
            room_name = names[zid]
            slot[room_name] = slot.get(room_name, 0.0) + amount

        old_amount = 0.0
        complete_stored = True
        for zid, samples in stored.items():
            current_stored = samples.get(t)
            prior_stored = samples.get(prev_t)
            if (
                current_stored is not None and prior_stored is not None
                and current_stored.get("sum") is not None
                and prior_stored.get("sum") is not None
            ):
                old_amount += max(
                    0.0, float(current_stored["sum"]) - float(prior_stored["sum"])
                )
            elif current_stored is not None and current_stored.get("state") is not None:
                old_amount += max(0.0, float(current_stored["state"]))
            else:
                complete_stored = False
        if complete_stored:
            stored_total += old_amount
        if not complete_stored or abs(old_amount - gas_kwh) > 0.05:
            stale_hours += 1
        hourly.append({
            "start_local": local.isoformat(timespec="minutes"),
            "vaillant_kwh": round(gas_kwh, 3),
            "stored_v2_kwh": round(old_amount, 3) if complete_stored else None,
            "current_allocated_kwh": round(gas_kwh - unknown, 3),
            "unallocated_kwh": round(unknown, 3),
            "difference_kwh": round(gas_kwh - old_amount, 3)
                if complete_stored else None,
            "stored_complete": complete_stored,
        })
        hour += timedelta(hours=1)

    if valid_hours == 0:
        return None
    return {
        "period": period,
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
        "unit": "kWh of estimated heating gas input",
        "source": "Live Vaillant hourly gas input + tado demand (Recorder, read-only)",
        "capacity_basis": "Installed radiator EN442 75/65/20, weighted by hourly tado demand",
        "data_mode": "live_reconciled",
        "complete": missing_hours == 0,
        "read_only": True,
        "source_hours": valid_hours,
        "missing_source_hours": missing_hours,
        "stale_stored_hours": stale_hours,
        "vaillant_heating_kwh": round(input_total, 3),
        "allocated_kwh": round(input_total - unknown_total, 3),
        "unallocated_kwh": round(unknown_total, 3),
        "legacy_stored_kwh": round(stored_total, 3),
        "legacy_difference_kwh": round(input_total - stored_total, 3),
        "rooms": list(names.values()),
        "series": [
            {"period": key, **{n: round(v, 3) for n, v in values.items()}}
            for key, values in sorted(timeline.items())
        ],
        "hourly_reconciliation": hourly,
        "note": (
            "Recent history is recomputed from CURRENT hourly source statistics. "
            "Previously published v2 external statistics are not modified and "
            "may contain stale gas amounts. Long ranges still use archived v2 "
            "estimates; a separate archival migration may be needed."
        ),
    }



async def detect_vaillant_hourly_start(
    hass, *, days: int = 120, tolerance_wh: float = 1.0,
    confirmation_days: int = 3,
) -> dict:
    """Find the earliest complete day whose hourly gas is not uniform.

    This is an *indicator*, not proof of measured hourlies: the same daily
    amount divided by 24 (or 23/25 at DST) produces suspiciously identical
    input deltas. Search the ORIGINAL myPyllant hourly heating profile; no
    tado statistics or other Recorder records are read or changed.
    """
    from datetime import time as date_time

    if not 3 <= days <= 365:
        raise HomeAssistantError("Scan days must be between 3 and 365")
    if not 0 <= tolerance_wh <= 50:
        raise HomeAssistantError("Hourly uniformity tolerance must be 0–50 Wh")
    if not 1 <= confirmation_days <= 7:
        raise HomeAssistantError("Confirmation days must be between 1 and 7")

    source_id = _gas_statistic(hass)
    if source_id is None:
        return {
            "status": "no_unique_vaillant_gas_heating_statistic",
            "read_only": True,
            "no_statistics_modified": True,
        }

    tz = ZoneInfo(hass.config.time_zone or "UTC")
    today = datetime.now(tz).date()
    first_day = today - timedelta(days=days)
    make_local = lambda d: datetime.combine(d, date_time.min, tzinfo=tz)
    start = make_local(first_day).astimezone(timezone.utc)
    end = make_local(today).astimezone(timezone.utc)
    fetched = await _fetch(
        hass, start - timedelta(hours=1), end, {source_id}, "hour"
    )
    sums = _rows_by_start(fetched.get(source_id))

    report = []
    daily_dates = []
    day = first_day
    while day < today:
        next_day = day + timedelta(days=1)
        start_utc = make_local(day).astimezone(timezone.utc)
        end_utc = make_local(next_day).astimezone(timezone.utc)
        expected = int((end_utc - start_utc).total_seconds() // 3600)
        values = []
        missing = 0
        for offset in range(expected):
            stamp = (start_utc + timedelta(hours=offset)).timestamp()
            current, previous = sums.get(stamp), sums.get(stamp - 3600)
            if current is None or previous is None or (
                current.get("sum") is None or previous.get("sum") is None
            ):
                missing += 1
                continue
            delta = float(current["sum"]) - float(previous["sum"])
            if not 0 <= delta <= 200000:
                missing += 1
                continue
            values.append(delta)
        if missing:
            classification = "incomplete"
        elif not values or sum(values) <= tolerance_wh:
            classification = "no_heating"
        elif max(values) - min(values) <= tolerance_wh:
            classification = "uniform_positive_suspected_backfill"
        else:
            classification = "nonuniform"

        sample = {
            "date": day.isoformat(),
            "classification": classification,
            "expected_hours": expected,
            "valid_hours": len(values),
            "missing_hours": missing,
            "heating_kwh": round(sum(values) * KWH_PER_WH, 3),
            "min_hour_kwh": round(min(values) * KWH_PER_WH, 4)
                if values else None,
            "max_hour_kwh": round(max(values) * KWH_PER_WH, 4)
                if values else None,
            "spread_wh": round(max(values) - min(values), 3)
                if values else None,
        }
        report.append(sample)
        daily_dates.append(day)
        day = next_day

    first_nonuniform = next(
        (i for i, r in enumerate(report) if r["classification"] == "nonuniform"),
        None
    )
    last_uniform = next((
        i for i in range(len(report) - 1, -1, -1)
        if report[i]["classification"] == "uniform_positive_suspected_backfill"
    ), None)
    stable_candidates = [
        i for i in range(len(report) - confirmation_days + 1)
        if all(
            report[k]["classification"] == "nonuniform"
            for k in range(i, i + confirmation_days)
        )
    ]
    first_stable = stable_candidates[0] if stable_candidates else None
    after_uniform = next((
        i for i in stable_candidates
        if last_uniform is not None and i > last_uniform
    ), None)
    cutoff = after_uniform if last_uniform is not None else first_stable
    anchor = cutoff if cutoff is not None else (
        last_uniform if last_uniform is not None else first_nonuniform
    )
    window = report[
        max(0, anchor - 6):min(len(report), anchor + 8)
    ] if anchor is not None else report[:min(14, len(report))]

    counts = {
        key: sum(r["classification"] == key for r in report)
        for key in (
            "uniform_positive_suspected_backfill", "nonuniform",
            "no_heating", "incomplete",
        )
    }
    first_data = next(
        (r["date"] for r in report if r["valid_hours"] > 0), None
    )
    return {
        "status": "hourly_uniformity_scan_completed",
        "read_only": True,
        "no_statistics_modified": True,
        "source": "Original myPyllant hourly Gas Heating Recorder statistic",
        "source_statistic_id": source_id,
        "timezone": str(tz),
        "scan_start_date": first_day.isoformat(),
        "scan_end_date_inclusive": (today - timedelta(days=1)).isoformat(),
        "days_scanned": days,
        "tolerance_wh": tolerance_wh,
        "confirmation_days": confirmation_days,
        "classification_counts": counts,
        "first_day_with_hourly_data": first_data,
        "first_complete_nonuniform_day": (
            report[first_nonuniform]["date"]
            if first_nonuniform is not None else None
        ),
        "first_consecutive_nonuniform_day": (
            report[first_stable]["date"] if first_stable is not None else None
        ),
        "last_uniform_positive_day": (
            report[last_uniform]["date"] if last_uniform is not None else None
        ),
        "candidate_cutoff_day": (
            report[cutoff]["date"] if cutoff is not None else None
        ),
        "candidate_is_proven_measured_hourly": False,
        "transition_window": window,
        "note": (
            "Equal positive hourly deltas suggest daily totals divided evenly "
            "into hourly buckets, but cannot prove how Vaillant generated them. "
            "The candidate is the first run of consecutive nonuniform days "
            "AFTER the last suspicious uniform-positive day in the scanned "
            "window (or the first such run if none were uniform). "
            "Missing and zero-heating days are not evidence of synthetic data. "
            "This action does not set a cutoff, delete records, or edit statistics."
        ),
    }


async def reconciliation_report(
    hass, main, date: str | None = None,
) -> dict:
    """Read-only hourly comparison for one Home Assistant calendar day."""
    tz = ZoneInfo(hass.config.time_zone or "UTC")
    if date is None:
        target_day = datetime.now(tz).date() - timedelta(days=1)
    else:
        from datetime import date as date_type
        try:
            target_day = date_type.fromisoformat(date)
        except (TypeError, ValueError) as err:
            raise HomeAssistantError("Date must be YYYY-MM-DD") from err
    start_local = datetime(
        target_day.year, target_day.month, target_day.day, tzinfo=tz
    )
    next_day = target_day + timedelta(days=1)
    end_local = datetime(
        next_day.year, next_day.month, next_day.day, tzinfo=tz
    )
    start, end = start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)
    cutoff = _allocation_cutoff(main)
    if cutoff is not None and start < cutoff:
        return {
            "status": "before_allocation_cutoff",
            "date": target_day.isoformat(),
            "cutoff_utc": cutoff.isoformat(),
            "read_only": True,
            "note": "Older synthetic room distributions are excluded. "
                    "Original Vaillant gas history is preserved.",
        }
    report = await _live_reconciled_history(
        hass, main, start, end, "day", "hour", tz
    )
    if report is None:
        return {
            "status": "no_reconcilable_hourly_data",
            "date": target_day.isoformat(),
            "read_only": True,
        }
    return {"status": "reconciliation_completed", "date": target_day.isoformat(), **report}


async def allocation_history(
    hass, main, period: str = "month", *,
    start_time: str | None = None, end_time: str | None = None,
) -> dict:
    """Read exact calendar ranges from Recorder; never modify source statistics.

    The managed dashboard uses inclusive local calendar days (exclusive end).
    Daily Recorder rows are requested even for multi-year views so a partial
    first/last month is not accidentally counted in full.
    """
    if period not in ("day", "week", "month", "year", "3years"):
        raise HomeAssistantError("Invalid history period")
    now = datetime.now(timezone.utc)
    tz = ZoneInfo(hass.config.time_zone or "UTC")
    if (start_time is None) != (end_time is None):
        raise HomeAssistantError("start_time and end_time must be supplied together")
    if start_time is not None:
        try:
            start = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            end = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
            if start.utcoffset() is None or end.utcoffset() is None:
                raise ValueError("Time zone offset is required")
            start = start.astimezone(timezone.utc)
            end = end.astimezone(timezone.utc)
        except (TypeError, ValueError) as err:
            raise HomeAssistantError("Invalid ISO 8601 history dates") from err
        if start >= end or end - start > timedelta(days=1099):
            raise HomeAssistantError("History range must be positive and at most 3 years")
        duration = end - start
        group = "hour" if duration <= timedelta(days=2) else (
            "day" if duration <= timedelta(days=92) else "month"
        )
    else:
        # Preserve backwards compatibility for service and standalone card users.
        days = {"day": 2, "week": 8, "month": 33,
                "year": 370, "3years": 1100}[period]
        end = now.replace(minute=0, second=0, microsecond=0)
        start = end - timedelta(days=days)
        group = ("month" if period in ("year", "3years") else
                 "day" if period in ("week", "month") else "hour")

    cutoff = _allocation_cutoff(main)
    if cutoff is not None:
        start = max(start, cutoff)
        if start >= end:
            return {
                "period": period,
                "start_time": start.isoformat(),
                "end_time": end.isoformat(),
                "rooms": [
                    *(str(z.get("name", z["id"])) for z in main.zones),
                    "Unallocated",
                ],
                "series": [],
                "data_mode": "no_data_before_cutoff",
                "cutoff_time": cutoff.isoformat(),
                "unit": "kWh of estimated heating gas input",
                "note": "Older room distributions were removed at the "
                        "configured allocation cutoff; original Vaillant "
                        "gas consumption remains available.",
            }

    # Recalculate bounded selections from the latest Vaillant source values,
    # rather than relying on append-only historic v2 room allocations.
    live = await _live_reconciled_history(hass, main, start, end, period, group, tz)
    if live is not None:
        return live

    # For precise custom ranges read daily rows and bucket them into months.
    # This avoids counting whole months outside a custom date range.
    query_period = "hour" if group == "hour" else "day"
    zones = {str(z["id"]): z.get("name", str(z["id"])) for z in main.zones}
    zones["unallocated"] = "Unallocated"
    ids = {_stat_id(main, zid) for zid in zones}
    stats = await _fetch(
        hass, start - timedelta(days=35), end, ids, query_period
    )
    timeline: dict[str, dict] = {}
    for zid, name in zones.items():
        rows = sorted(stats.get(_stat_id(main, zid), []),
                      key=lambda row: row["start"])
        # A cutoff migration rebases this complete derived series to zero.
        previous = 0.0 if cutoff is not None and start == cutoff else None
        for row in rows:
            dt = _hour(row["start"])
            if dt < start:
                previous = row.get("sum")
                continue
            if dt >= end:
                break
            if previous is not None and row.get("sum") is not None:
                delta = max(0, float(row["sum"]) - float(previous))
                local = dt.astimezone(tz)
                key = (local.strftime("%Y-%m") if group == "month" else
                       local.strftime("%Y-%m-%d") if group == "day" else
                       local.strftime("%Y-%m-%dT%H:00"))
                slot = timeline.setdefault(key, {})
                slot[name] = round(slot.get(name, 0) + delta, 3)
            previous = row.get("sum")
    return {
        "period": period,
        "start_time": start.isoformat(), "end_time": end.isoformat(),
        "unit": "kWh of estimated heating gas input",
        "source": "Vaillant hourly gas heating profile allocated by tado room demand",
        "capacity_basis": "Installed radiator EN442 75/65/20, v2 separate statistic IDs",
        "rooms": list(zones.values()),
        "series": [{"period": key, **value}
                   for key, value in sorted(timeline.items())],
        "note": "No history exists before the allocation service began recording. This does not measure radiator heat output.",
    }


async def diagnose_unallocated(hass, main, *, days: int = 35,
                               limit: int = 30) -> dict:
    """Explain each unallocated gas-input hour without changing any statistics.

    Mirrors allocate_recent()'s source, UTC bucket alignment and decision
    tree. Separately counts unknown/invalid room measurements and genuine
    all-zero room demand. Reports highest-energy hours and daily breakdowns,
    plus adjacent-hour activity as a clue to timing; it does not reallocate.
    """
    if not 1 <= days <= MAX_BACKFILL_DAYS:
        raise HomeAssistantError("Diagnostic days must be 1–35")
    if not 1 <= limit <= 100:
        raise HomeAssistantError("Diagnostic limit must be 1–100")
    if not getattr(main, "is_x", False):
        raise HomeAssistantError("Unallocated heating diagnostic requires tado X")
    source_id = _gas_statistic(hass)
    if source_id is None:
        return {
            "status": "no_unique_vaillant_gas_heating_statistic",
            "read_only": True,
            "message": "Requires the running myPyllant hourly Gas Heating profile.",
        }
    room_sensors = _room_sensor_ids(hass, main)
    names = {str(z["id"]): str(z.get("name", z["id"])) for z in main.zones}
    if len(room_sensors) != len(main.zones):
        return {
            "status": "room_heating_sensors_not_ready", "read_only": True,
            "rooms_found": len(room_sensors), "rooms_expected": len(main.zones),
        }

    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    cutoff = _allocation_cutoff(main)
    start = max(end - timedelta(days=days), cutoff) if cutoff else (
        end - timedelta(days=days)
    )
    if start >= end:
        return {"status": "no_hours_after_cutoff", "read_only": True,
                "unallocated_kwh": 0, "days": days}
    # One hour before for the Vaillant cumulative gas delta; one after for a
    # comparison with the following tado room-demand hour when available.
    snapshots = await _fetch(
        hass, start - timedelta(hours=1), end + timedelta(hours=1),
        set(room_sensors.values()) | {source_id},
    )
    source = _rows_by_start(snapshots.get(source_id))
    room_history = {
        zid: _rows_by_start(snapshots.get(entity_id))
        for zid, entity_id in room_sensors.items()
    }

    categories = {
        "missing_or_invalid_room_demand": {"hours": 0, "gas_kwh": 0.0,
                                           "hours_with_other_rooms_active": 0},
        "all_rooms_zero_demand": {"hours": 0, "gas_kwh": 0.0,
                                  "hours_with_adjacent_demand": 0},
    }
    missing_by_room = {
        zid: {"room": names[zid], "hours": 0, "gas_kwh_affected": 0.0}
        for zid in room_sensors
    }
    daily: dict[str, dict] = {}
    details = []
    valid_hours = 0
    valid_gas_kwh = 0.0
    unallocated = 0.0
    skipped_gas_hours = 0
    for idx in range(int((end-start).total_seconds() // 3600)):
        hour = start + timedelta(hours=idx)
        t = hour.timestamp()
        previous_t = t - 3600
        current, previous = source.get(t), source.get(previous_t)
        if (current is None or previous is None
                or current.get("sum") is None or previous.get("sum") is None):
            skipped_gas_hours += 1
            continue
        diff = float(current["sum"]) - float(previous["sum"])
        if not 0 <= diff <= 200000:
            skipped_gas_hours += 1
            continue
        gas_kwh = diff * KWH_PER_WH
        valid_hours += 1
        valid_gas_kwh += gas_kwh
        if gas_kwh <= 0:
            continue

        room_values = {}
        missing = []
        positive = []
        for zid, row_map in room_history.items():
            row = row_map.get(t)
            raw_value = row.get("mean") if row is not None else None
            try:
                val = float(raw_value) if raw_value is not None else None
            except (TypeError, ValueError):
                val = None
            if val is None or not 0 <= val <= 100:
                missing.append(zid)
            else:
                room_values[zid] = val
                if val > 0:
                    positive.append(zid)
        if not missing and positive:
            continue

        reason = ("missing_or_invalid_room_demand" if missing
                  else "all_rooms_zero_demand")
        bucket = categories[reason]
        bucket["hours"] += 1
        bucket["gas_kwh"] += gas_kwh
        unallocated += gas_kwh

        previous_hour_active = any(
            row_map.get(t - 3600) is not None
            and isinstance(row_map[t - 3600].get("mean"), (int, float))
            and row_map[t - 3600]["mean"] > 0
            for row_map in room_history.values()
        )
        next_hour_active = any(
            row_map.get(t + 3600) is not None
            and isinstance(row_map[t + 3600].get("mean"), (int, float))
            and row_map[t + 3600]["mean"] > 0
            for row_map in room_history.values()
        )
        if missing:
            if positive:
                bucket["hours_with_other_rooms_active"] += 1
            for zid in missing:
                missing_by_room[zid]["hours"] += 1
                missing_by_room[zid]["gas_kwh_affected"] += gas_kwh
        elif previous_hour_active or next_hour_active:
            bucket["hours_with_adjacent_demand"] += 1

        local = hour.astimezone(ZoneInfo("Europe/Brussels"))
        date_key = local.strftime("%Y-%m-%d")
        day = daily.setdefault(date_key, {
            "date": date_key,
            "gas_kwh_unallocated": 0.0,
            "missing_demand_kwh": 0.0,
            "zero_demand_kwh": 0.0,
            "hours": 0,
        })
        day["gas_kwh_unallocated"] += gas_kwh
        day["hours"] += 1
        day["missing_demand_kwh" if missing else "zero_demand_kwh"] += gas_kwh
        details.append({
            "start_local": local.isoformat(timespec="minutes"),
            "start_utc": hour.isoformat(timespec="minutes"),
            "reason": reason,
            "gas_kwh": round(gas_kwh, 3),
            "missing_rooms": [names[zid] for zid in missing],
            "positive_demand_rooms": [
                {"room": names[zid], "demand_percent": round(room_values[zid], 1)}
                for zid in positive
            ],
            "previous_hour_any_room_active": previous_hour_active,
            "next_hour_any_room_active": next_hour_active,
        })

    for category in categories.values():
        category["gas_kwh"] = round(category["gas_kwh"], 3)
    for row in missing_by_room.values():
        row["gas_kwh_affected"] = round(row["gas_kwh_affected"], 3)
    for row in daily.values():
        for key in ("gas_kwh_unallocated", "missing_demand_kwh",
                    "zero_demand_kwh"):
            row[key] = round(row[key], 3)
    missing_ranking = sorted(
        [v for v in missing_by_room.values() if v["hours"]],
        key=lambda row: (-row["gas_kwh_affected"], row["room"]),
    )
    return {
        "status": "diagnostic_completed",
        "read_only": True,
        "days": days,
        "period_start_utc": start.isoformat(timespec="minutes"),
        "period_end_utc": end.isoformat(timespec="minutes"),
        "gas_profile": source_id,
        "gas_kwh_in_valid_hours": round(valid_gas_kwh, 3),
        "valid_gas_hours": valid_hours,
        "skipped_gas_hours": skipped_gas_hours,
        "unallocated_kwh": round(unallocated, 3),
        "unallocated_percent": round(
            100 * unallocated / valid_gas_kwh, 2
        ) if valid_gas_kwh else 0,
        "causes": categories,
        "missing_room_breakdown": missing_ranking,
        "days_with_unallocated": sorted(
            daily.values(),
            key=lambda row: (-row["gas_kwh_unallocated"], row["date"]),
        ),
        "highest_unallocated_hours": sorted(
            details, key=lambda row: (-row["gas_kwh"], row["start_utc"])
        )[:limit],
        "total_unallocated_hours": len(details),
        "explanation": (
            "Missing demand for even one room assigns the whole hour to "
            "Unallocated. All-zero demand with Vaillant gas input is the "
            "other cause. Adjacent-hour activity is a timing clue, not proof. "
            "All amounts are gas INPUT, not measured room heat. This service "
            "does not change historic or current allocations."
        ),
    }
