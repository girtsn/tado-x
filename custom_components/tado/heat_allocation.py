"""Estimated heating-gas allocation to tado rooms using existing HA Recorder.

Input energy: myPyllant's ORIGINAL hourly gas HEATING external statistic (Wh).
Input activity: Recorder hourly mean of each tado room's heating demand (%).
Output: NEW, separate tado: external statistics (kWh of attributed gas input).

This is NOT radiator thermal output, not measured valve travel and not actual
individual radiator energy. No Vaillant recorder/statistic/source is modified.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from collections import defaultdict
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

_LOGGER = logging.getLogger(__name__)
PREFIX = "tado:x_estimated_gas_heating_"
GAS_PROFILE = ("CONSUMED_PRIMARY_ENERGY", "HEATING")
KWH_PER_WH = 0.001
MAX_BACKFILL_DAYS = 35


def _stat_id(main, zone_id: int | str) -> str:
    return f"{PREFIX}{main.home_id}_{zone_id}"


def _capacities(main) -> dict[str, float]:
    overrides = main.config_entry.options.get("x_capacity_kw", {})
    result = {}
    for room in main.zones:
        room_id = str(room["id"])
        devices = room.get("devices", [])
        count = sum(
            1 for d in devices
            if isinstance(d, dict)
            and str(d.get("type", d.get("deviceType", ""))).startswith("VA")
        )
        default = float(max(count, 1))  # equal relative radiator capacity
        stored = overrides.get(room_id)
        result[room_id] = float(stored) if type(stored) in (int, float) and stored > 0 else default
    return result


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
    cap = _capacities(main)
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
                prior_sum = new[zid][-1].sum
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
        "rooms": list(zones.values()),
        "series": [{"period":key,**value} for key,value in sorted(timeline.items())],
        "note": "No history exists before the allocation service began recording. This does not measure radiator heat output.",
    }
