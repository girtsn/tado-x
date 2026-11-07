"""Estimated heating-gas allocation to tado rooms using existing HA Recorder.

Input energy: myPyllant's ORIGINAL hourly gas HEATING external statistic (Wh).
Input activity: Recorder hourly mean of each tado room's heating demand (%).
Output: NEW, separate tado: external statistics (kWh of attributed gas input).

This is NOT radiator thermal output, not measured valve travel and not actual
individual radiator energy. No Vaillant recorder/statistic/source is modified.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
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


def _stat_id(main, zone_id: int | str) -> str:
    return f"{PREFIX}{main.home_id}_{zone_id}"


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


async def allocate_recent(hass, main, *, days: int = 3, dry_run: bool = False) -> dict:
    """Append only completed hours; never rewrite existing recorder rows.

    The first publish attempt should cover periods during which both source
    myPyllant statistics and tado heating activity statistics are available.
    """
    if not 1 <= days <= MAX_BACKFILL_DAYS:
        raise HomeAssistantError("Backfill days must be between 1 and 35")
    if not getattr(main, "is_x", False):
        raise HomeAssistantError("Heating allocation requires tado X")
    source_id = _gas_statistic(hass)
    if source_id is None:
        return {"status": "no_unique_vaillant_gas_heating_statistic",
                "message": "Requires a running myPyllant hourly Gas Heating profile."}
    room_sensors = _room_sensor_ids(hass, main)
    if len(room_sensors) != len(main.zones):
        return {"status": "room_heating_sensors_not_ready",
                "rooms_found": len(room_sensors), "rooms_expected": len(main.zones)}

    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(days=days)
    try:
        cap = _capacities(main)
    except HomeAssistantError as err:
        report = radiator_capacity_report(main.zones, main.config_entry.options.get("x_capacity_kw", {}),
        main.config_entry.options.get("x_radiator_room_mapping", {}))
        return {
            "status": "radiator_capacity_mapping_needs_review",
            "message": str(err),
            "rooms": report["rooms"],
            "no_statistics_modified": True,
        }
    stat_ids = set(room_sensors.values()) | {source_id}
    output_ids = {_stat_id(main, zid) for zid in room_sensors}
    output_ids.add(_stat_id(main, "unallocated"))
    snapshots = await _fetch(hass, start - timedelta(hours=1), end,
                             stat_ids | output_ids)
    source = _rows_by_start(snapshots.get(source_id))
    rooms = {zid: _rows_by_start(snapshots.get(entity_id))
             for zid, entity_id in room_sensors.items()}
    outputs = {zid: _rows_by_start(snapshots.get(_stat_id(main, zid)))
               for zid in (*room_sensors, "unallocated")}
    hours = [start + timedelta(hours=i)
             for i in range(int((end-start).total_seconds()//3600))]
    new: dict[str, list] = {key: [] for key in outputs}
    allocated_kwh, unknown_kwh, total_kwh = 0.0, 0.0, 0.0
    processed = 0
    for hour_start in hours:
        t = hour_start.timestamp()
        old_t = (hour_start - timedelta(hours=1)).timestamp()
        gas = source.get(t)
        gas_prev = source.get(old_t)
        if not gas or not gas_prev:
            continue
        if gas.get("sum") is None or gas_prev.get("sum") is None:
            continue
        delta_wh = float(gas["sum"]) - float(gas_prev["sum"])
        if not 0 <= delta_wh <= 200000:
            # Counter reset or unexpected input; never invent gas quantities.
            continue
        gas_kwh = delta_wh * KWH_PER_WH
        means = {zid: room[t]["mean"] if t in room and room[t].get("mean") is not None else None
                 for zid, room in rooms.items()}
        if any(v is None or not 0 <= v <= 100 for v in means.values()):
            shares = {zid: 0.0 for zid in room_sensors}
            unknown = gas_kwh
        else:
            weights = {zid: float(v)*cap[zid] for zid, v in means.items()}
            total_w = sum(weights.values())
            shares = {zid: gas_kwh*value/total_w if total_w>0 else 0.0
                      for zid, value in weights.items()}
            unknown = gas_kwh if total_w == 0 else 0.0

        totals = {**shares, "unallocated": unknown}
        # Recorder sum should remain monotone. Never insert an older record
        # before a newer published row: it would require a rebasing rewrite.
        if any(any(s > t for s in outputs[zid]) for zid in outputs):
            continue
        if all(t in outputs[zid] for zid in outputs):
            continue

        for zid, value in totals.items():
            if t in outputs[zid]:
                continue
            prior = [r for start_time, r in outputs[zid].items()
                     if start_time < t and r.get("sum") is not None]
            prior_sum = float(prior[-1]["sum"]) if prior else 0.0
            # Also account for earlier NEW rows from this call.
            if new[zid]:
                prior_sum = new[zid][-1]["sum"]
            row = StatisticData(start=hour_start, state=value, sum=prior_sum+value)
            new[zid].append(row)
        processed += 1
        total_kwh += gas_kwh
        allocated_kwh += gas_kwh-unknown
        unknown_kwh += unknown

    if not dry_run:
        names = {str(z["id"]): z.get("name",str(z["id"])) for z in main.zones}
        names["unallocated"] = "Unallocated / no room demand"
        for zid, rows in new.items():
            if rows:
                async_add_external_statistics(hass, _meta(main, zid, names[zid]), rows)
    return {
        "status": "estimated_hours_published" if not dry_run else "dry_run",
        "hours": processed, "gas_heating_kwh": round(total_kwh,3),
        "allocated_kwh": round(allocated_kwh,3),
        "unallocated_kwh": round(unknown_kwh,3),
        "source": "myPyllant Gas Heating (Wh) + tado heating demand hourly means",
        "capacity_basis": "EN442 75/65/20 radiator output, room sum for multiple radiators",
        "capacity_kw": cap,
        "interpretation": "Estimated allocation of gas INPUT, not thermal energy per radiator",
    }


async def allocation_history(hass, main, period: str = "month") -> dict:
    """Read the new external series; low-volume daily or monthly aggregates."""
    if period not in ("day", "week", "month", "year", "3years"):
        raise HomeAssistantError("Invalid history period")
    now = datetime.now(timezone.utc)
    days = {"day": 2, "week": 8, "month": 33, "year": 370, "3years": 1100}[period]
    period_key = "month" if period in ("year", "3years") else "day" if period in ("week","month") else "hour"
    end = now.replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(days=days)
    zones = {str(z["id"]): z.get("name",str(z["id"])) for z in main.zones}
    zones["unallocated"] = "Unallocated"
    ids = {_stat_id(main,zid) for zid in zones}
    stats = await _fetch(hass, start-timedelta(days=35), end, ids, period_key)
    timeline: dict[str, dict] = {}
    for zid,name in zones.items():
        rows = sorted(stats.get(_stat_id(main,zid), []), key=lambda r:r["start"])
        previous = None
        for row in rows:
            dt = _hour(row["start"]).astimezone(ZoneInfo("Europe/Brussels"))
            if dt < start.astimezone(ZoneInfo("Europe/Brussels")):
                previous = row.get("sum")
                continue
            if previous is not None and row.get("sum") is not None:
                delta = max(0, float(row["sum"])-float(previous))
                key = dt.strftime("%Y-%m") if period_key=="month" else dt.strftime("%Y-%m-%d") if period_key=="day" else dt.strftime("%Y-%m-%dT%H:00")
                slot=timeline.setdefault(key,{})
                slot[name]=round(slot.get(name,0)+delta,3)
            previous=row.get("sum")
    return {
        "period": period,
        "unit": "kWh of estimated heating gas input",
        "source": "Vaillant hourly gas heating profile allocated by tado room demand",
        "capacity_basis": "Installed radiator EN442 75/65/20, v2 separate statistic IDs",
        "rooms": list(zones.values()),
        "series": [{"period":key,**value} for key,value in sorted(timeline.items())],
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
    start = end - timedelta(days=days)
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
    for idx in range(days * 24):
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
