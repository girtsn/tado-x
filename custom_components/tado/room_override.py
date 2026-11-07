"""Read-only Tado X room schedule/override detection.

PyTado 0.18.15's TadoXZone.from_data maps HOPS room
manualControlTermination != null to zone.overlay_active = True.
Do not compare current setpoint to scheduled temperature: same setpoint can
still be a manual override, while a scheduled room can be currently OFF.

Room state refers to a tado ROOM, not individual radiator valve devices.
"""
from __future__ import annotations

from typing import Any


def _read_zone(zone: Any) -> tuple[str, str | None]:
    """Return (state, termination), never guess when state is ambiguous.

    state: 'manual_override' | 'smart_schedule' | 'unknown'
    """
    if zone is None:
        return "unknown", None
    if isinstance(zone, dict):
        if zone.get("available") is False:
            return "unknown", None
        if "manualControlTermination" in zone:
            control = zone["manualControlTermination"]
            return (
                ("manual_override", control.get("type"))
                if isinstance(control, dict)
                else ("smart_schedule", None)
                if control is None
                else ("unknown", None)
            )
        if type(zone.get("overlay_active")) is bool:
            return (
                "manual_override" if zone["overlay_active"] else "smart_schedule",
                zone.get("overlay_termination_type"),
            )
        mode = zone.get("current_hvac_mode")
        if mode == "SMART_SCHEDULE":
            return "smart_schedule", None
        if mode in ("HEAT", "OFF") and zone.get("overlay_termination_type"):
            return "manual_override", zone["overlay_termination_type"]
        return "unknown", None
    if getattr(zone, "available", True) is False:
        return "unknown", None
    active = getattr(zone, "overlay_active", None)
    if type(active) is bool:
        return (
            "manual_override" if active else "smart_schedule",
            getattr(zone, "overlay_termination_type", None) if active else None,
        )
    return "unknown", None


def _room_power(zone: Any) -> str | None:
    """Use the reported heating power, never temperature/demand as a proxy."""
    if zone is None:
        return None
    if isinstance(zone, dict):
        setting = zone.get("setting")
        power = setting.get("power") if isinstance(setting, dict) else zone.get("power")
    else:
        power = getattr(zone, "power", None)
    return power if power in ("ON", "OFF") else None


def observed_home_mode(report: dict, last_action: dict | None = None) -> dict:
    """Combine actual room overlay states and persisted, requested boost.

    A quick-action boost cannot be differentiated from manually overriding
    all rooms by room state alone; the persisted timer is explicit evidence
    only that HA initiated that boost. Prioritise independently observed
    schedule/override status over the last requested HA action. Do not
    mislabel a scheduled OFF interval as Heating Off.
    """
    last_action = last_action or {}
    count = report["total_rooms"]
    unknown = report["unknown_count"]
    manual = report["manual_override_count"]
    scheduled = report["schedule_count"]
    off = report["manual_off_count"]
    active_boost = (
        last_action.get("pending") is True
        and last_action.get("kind") == "resume_and_adapt"
        and last_action.get("mode") in ("eco_boost", "top_boost")
    )
    if not count or unknown:
        status = "unknown"
        label = "Room state incomplete" if count else "Room state unavailable"
    elif manual == 0:
        status, label = "schedule", "Following Schedules"
    elif off == count:
        status, label = "off", "Heating Off"
    else:
        status, label = "manual_override", f"Manual Override ({manual})"

    if active_boost and status == "manual_override":
        # Report the timed boost while preserving observed manual room status.
        effective = last_action["mode"]
        effective_label = last_action.get("mode_label") or (
            "Eco Boost" if effective == "eco_boost" else "Top Boost"
        )
    else:
        effective, effective_label = status, label

    return {
        "observed_mode": status,
        "observed_mode_label": label,
        "effective_mode": effective,
        "effective_mode_label": effective_label,
        "observed_room_states": count - unknown,
        "boost_timer_active": active_boost,
        "reported_manual_off_count": off,
        # Only a confirmed interruption or known disabled adaptation is a
        # reason to resume; unknown data is not falsely treated as a change.
        "room_schedule_interrupted": manual > 0,
    }


def room_override_report(coordinator) -> dict:
    """Summarise room overrides using only the existing 5-minute zone cache."""
    config = getattr(coordinator, "zones", ()) or ()
    data = getattr(coordinator, "data", {}) or {}
    states = data.get("zone") or {}
    result = []
    for zone in config:
        zid = int(zone["id"])
        name = zone.get("name") or zone.get("roomName") or str(zid)
        zstate = states.get(zid) if isinstance(states, dict) else None
        if zstate is None and isinstance(states, dict):
            zstate = states.get(str(zid))
        status, termination = _read_zone(zstate)
        power = _room_power(zstate)
        result.append({
            "room_id": zid,
            "room": str(name),
            "state": status,
            "termination": termination,
            "power": power,
        })
    overridden = [item["room"] for item in result if item["state"] == "manual_override"]
    scheduled = [item["room"] for item in result if item["state"] == "smart_schedule"]
    unknown = [item["room"] for item in result if item["state"] == "unknown"]
    manual_off = [item["room"] for item in result if item["state"] == "manual_override"
                  and item["power"] == "OFF"]
    return {
        "total_rooms": len(result),
        "manual_override_count": len(overridden),
        "schedule_count": len(scheduled),
        "unknown_count": len(unknown),
        "manual_off_count": len(manual_off),
        "manual_off_rooms": manual_off,
        "manual_override_rooms": overridden,
        "unknown_rooms": unknown,
        "rooms": result,
        "all_following_schedules": bool(result) and not overridden and not unknown,
        "has_manual_override": bool(overridden),
        "source": "cached_tado_x_room_overlay_active",
        "source_is_room_not_individual_valve": True,
    }
