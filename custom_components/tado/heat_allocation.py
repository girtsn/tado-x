"""Estimated heating-gas allocation to tado rooms using existing HA Recorder.

Input energy: myPyllant's ORIGINAL hourly gas HEATING external statistic (Wh).
Input activity: Recorder hourly mean of each tado room's heating demand (%).
Output: NEW, separate tado: external statistics (kWh of attributed gas input).

This is NOT radiator thermal output, not measured valve travel and not actual
individual radiator energy. No Vaillant recorder/statistic/source is modified.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
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


async def allocation_history(
    hass, main, period: str = "month",
    *, start_date: str | None = None, end_date: str | None = None,
) -> dict:
    """Read room gas-input estimates for exact Brussels-local calendar dates.

    Inclusive start_date/end_date are YYYY-MM-DD. A short selection reads
    actual hourly Recorder estimates, bucketing them into Brussels days
    (including DST's 23/25-hour days). Long selections read recorder monthly
    totals for complete months, plus exact hourly boundary months, so
    arbitrary custom date ranges are not silently rounded to whole months.
    No tado or Vaillant cloud calls, no writes, and no synthetic values.
    """
    valid = ("day", "week", "month", "year", "3years", "custom")
    if period not in valid:
        raise HomeAssistantError("Invalid history period")
    tz = ZoneInfo(hass.config.time_zone or "Europe/Brussels")
    now = datetime.now(timezone.utc)
    today = now.astimezone(tz).date()
    if (start_date is None) != (end_date is None):
        raise HomeAssistantError("Both start_date and end_date are required")
    if start_date is None:
        # Backward compatibility for existing clients calling only 'period'.
        fallback = {"day": 2, "week": 8, "month": 33,
                    "year": 370, "3years": 1100, "custom": 33}[period]
        start_day = (now - timedelta(days=fallback)).astimezone(tz).date()
        end_day = today
    else:
        try:
            start_day = date.fromisoformat(start_date)
            end_day = date.fromisoformat(end_date)
        except (TypeError, ValueError) as err:
            raise HomeAssistantError("Dates must be YYYY-MM-DD") from err
        if (start_day.isoformat() != start_date or
                end_day.isoformat() != end_date):
            raise HomeAssistantError("Dates must be YYYY-MM-DD")
    if start_day > end_day:
        raise HomeAssistantError("start_date must be on/before end_date")
    if (end_day - start_day).days > 1120:
        raise HomeAssistantError("Date range cannot exceed 1121 days")
    if end_day > today:
        end_day = today
    zones = {str(z["id"]): z.get("name", str(z["id"])) for z in main.zones}
    zones["unallocated"] = "Unallocated"
    timeline: dict[str, dict[str, float]] = {}
    if start_day > today:
        return {
            "period": period, "rooms": list(zones.values()), "series": [],
            "range_start": start_date, "range_end": end_day.isoformat(),
            "aggregation": "day", "status": "future_period",
            "unit": "kWh of estimated heating gas input",
        }

    begin_local = datetime.combine(start_day, time.min, tzinfo=tz)
    end_local = datetime.combine(end_day + timedelta(days=1), time.min, tzinfo=tz)
    begin = begin_local.astimezone(timezone.utc)
    end = min(end_local.astimezone(timezone.utc), now.replace(
        minute=0, second=0, microsecond=0))
    if begin >= end:
        return {
            "period": period, "rooms": list(zones.values()), "series": [],
            "range_start": start_day.isoformat(), "range_end": end_day.isoformat(),
            "aggregation": "day", "status": "no_completed_hours",
            "unit": "kWh of estimated heating gas input",
        }

    length_days = (end_day - start_day).days + 1
    use_months = period in ("year", "3years") or length_days > 93
    grouping = "hour" if period == "day" else "month" if use_months else "day"
    ids = {_stat_id(main, zid) for zid in zones}

    def accept(zid: str, stamp: datetime, amount: float) -> None:
        if not (amount >= 0 and amount < 200000):
            return
        local = stamp.astimezone(tz)
        if not begin <= stamp < end:
            return
        if grouping == "hour":
            # Include UTC offset in keys: autumn's repeated 02:00 has TWO
            # distinct recorded hours and must never be collapsed.
            key = local.isoformat(timespec="minutes")
        elif grouping == "month":
            key = local.strftime("%Y-%m")
        else:
            key = local.strftime("%Y-%m-%d")
        slot = timeline.setdefault(key, {})
        name = zones[zid]
        slot[name] = slot.get(name, 0.0) + amount

    async def hourly_between(start: datetime, finish: datetime) -> None:
        if finish <= start:
            return
        snapshots = await _fetch(hass, start - timedelta(hours=1), finish, ids, "hour")
        for zid in zones:
            rows = sorted(snapshots.get(_stat_id(main, zid), []),
                          key=lambda r: r["start"])
            previous = None
            for row in rows:
                if previous is not None and row.get("sum") is not None and previous.get("sum") is not None:
                    stamp = _hour(row["start"])
                    step = float(row["start"]) - float(previous["start"])
                    if 3599 <= step <= 3601 and start <= stamp < finish:
                        delta = float(row["sum"]) - float(previous["sum"])
                        if delta >= -0.0001:
                            accept(zid, stamp, max(0.0, delta))
                previous = row

    if not use_months:
        await hourly_between(begin, end)
    else:
        first_month = begin_local.replace(day=1)
        final_month = end_local.replace(day=1)
        next_first_month = (
            first_month.replace(year=first_month.year + 1, month=1)
            if first_month.month == 12
            else first_month.replace(month=first_month.month + 1)
        )
        # Full months: use compact Recorder monthly statistics, no huge
        # 3-year hourly read. The first and last partial months are handled
        # independently using the hourly rows.
        month_stats = await _fetch(
            hass, first_month.astimezone(timezone.utc) - timedelta(days=40),
            end, ids, "month")
        for zid in zones:
            rows = sorted(month_stats.get(_stat_id(main, zid), []),
                          key=lambda r: r["start"])
            previous = None
            for row in rows:
                if previous is not None and row.get("sum") is not None and previous.get("sum") is not None:
                    stamp = _hour(row["start"])
                    local = stamp.astimezone(tz)
                    local_month = local.replace(day=1, hour=0, minute=0,
                                                second=0, microsecond=0)
                    month_after = (
                        local_month.replace(year=local_month.year + 1, month=1)
                        if local_month.month == 12
                        else local_month.replace(month=local_month.month + 1)
                    )
                    # Entire month must be within selected period, and be
                    # finished. The ongoing current month is an hourly edge.
                    if (local_month.astimezone(timezone.utc) >= begin
                            and month_after.astimezone(timezone.utc) <= end):
                        delta = float(row["sum"]) - float(previous["sum"])
                        if delta >= -0.0001:
                            accept(zid, stamp, max(0.0, delta))
                previous = row
        if begin > first_month.astimezone(timezone.utc):
            await hourly_between(begin, min(
                end, next_first_month.astimezone(timezone.utc)))
        # Incomplete last month (can be the same month as the first). No
        # double count if it was entirely covered by the first edge.
        final_start = final_month.astimezone(timezone.utc)
        final_after = (
            final_month.replace(year=final_month.year + 1, month=1)
            if final_month.month == 12 else
            final_month.replace(month=final_month.month + 1)
        ).astimezone(timezone.utc)
        if end > final_start and end < final_after:
            await hourly_between(max(begin, final_start,
                                     next_first_month.astimezone(timezone.utc)
                                     if begin > first_month.astimezone(timezone.utc)
                                     else begin), end)

    return {
        "period": period,
        "range_start": start_day.isoformat(),
        "range_end": end_day.isoformat(),
        "aggregation": grouping,
        "unit": "kWh of estimated heating gas input",
        "source": "Existing Vaillant-based room allocation statistics",
        "capacity_basis": "EN442 rated radiator output, v2 estimates",
        "rooms": list(zones.values()),
        "series": [
            {"period": key, **{name: round(value, 5) for name, value in values.items()}}
            for key, values in sorted(timeline.items())
        ],
        "note": (
            "Selected dates are inclusive in Home Assistant local time. "
            "No synthetic missing history or future consumption is added. "
            "Historic hours reconstructed from daily Vaillant totals remain "
            "provisional room allocation."
        ),
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
