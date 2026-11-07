"""Opt-in tado X (HOPS) settings and schedule access.

All requests reuse the existing PyTado OAuth session under the coordinator's
serialised API lock. Never create another login or log response bodies.
Unpublished endpoints are treated as experimental. Writes happen ONLY on an
explicit Home Assistant service/entity action, never during polling.
"""

from __future__ import annotations

from datetime import timedelta
import hashlib
import json
import logging
import math
import re
from typing import Any

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

_LOGGER = logging.getLogger(__name__)
BASE_URL = "https://hops.tado.com"
DAYS = ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY")
TIME_RE = re.compile(r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
X_POLL_INTERVAL = timedelta(minutes=30)


def _request(client: Any, home_id: int, method: str, endpoint: str,
             payload: dict | None = None) -> Any:
    """Synchronous request: call exclusively through coordinator._async_tado_call."""
    http = client._http
    http._refresh_token()
    auth = http._headers.get("Authorization")
    if not isinstance(auth, str) or not auth.startswith("Bearer "):
        raise HomeAssistantError("tado X OAuth session is unavailable")
    if method not in {"GET", "POST", "PATCH"}:
        raise HomeAssistantError("Unsupported tado X operation")
    response = http._session.request(
        method,
        f"{BASE_URL}/homes/{home_id}/{endpoint}",
        headers={
            "Authorization": auth,
            "User-Agent": http._headers.get("user-agent", "HomeAssistant/tado-x"),
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        params={"ngsw-bypass": "true"},
        json=payload,
        timeout=12,
        allow_redirects=False,
    )
    if response.status_code == 404 and method == "GET":
        return None
    if response.status_code not in (200, 201, 202, 204):
        # No raw API response: it may contain account/device identifiers.
        raise HomeAssistantError(
            f"tado X {method} {endpoint.split('/')[0]} returned HTTP {response.status_code}"
        )
    if response.status_code == 204 or not response.content:
        return {}
    try:
        return response.json()
    except ValueError as err:
        raise HomeAssistantError("tado X API returned invalid JSON") from err


class TadoXClient:
    """One transport shared with the running core tado integration."""

    def __init__(self, coordinator) -> None:
        self.coordinator = coordinator
        if not coordinator.is_x:
            raise HomeAssistantError("This feature requires tado X")

    def _room(self, room_id: int) -> int:
        if type(room_id) is not int or room_id not in {
            int(z["id"]) for z in self.coordinator.zones if "id" in z
        }:
            raise HomeAssistantError("Room is not part of this tado X home")
        return room_id

    async def call(self, method: str, endpoint: str, payload: dict | None = None):
        return await self.coordinator._async_tado_call(
            _request, self.coordinator._tado, self.coordinator.home_id,
            method, endpoint, payload,
        )

    async def get_schedule(self, room_id: int):
        return await self.call("GET", f"rooms/{self._room(room_id)}/schedule")

    async def save_day(self, room_id: int, day: str, blocks: list[dict],
                       expected_signature: str) -> dict:
        """Optimistic read/compare/write/read to avoid stale schedule overwrites."""
        self._room(room_id)
        if day not in DAYS:
            raise HomeAssistantError("Invalid weekday")
        payload = make_day_payload(day, blocks)
        old = await self.get_schedule(room_id)
        old_day = canonical_day(old, day)
        if schedule_signature(old_day) != expected_signature:
            raise HomeAssistantError(
                "tado schedule changed since it was loaded: reload before saving"
            )
        await self.call("POST", f"rooms/{room_id}/schedule", payload)
        actual = await self.get_schedule(room_id)
        requested = canonical_day(payload["daySchedule"], day)
        confirmed = canonical_day(actual, day) == requested
        return {"confirmed": confirmed, "room_id": room_id, "day": day,
                "signature": schedule_signature(canonical_day(actual, day))}

    async def heating_quick_action(self, action: str) -> dict:
        """Perform an explicit whole-home heating quick action (one HOPS POST).

        These commands do not control domestic hot water, and Boost Heating
        does NOT intentionally change flow-temperature auto adaptation.
        """
        paths = {
            "off": "quickActions/allOff",
            "resume": "quickActions/resumeSchedule",
            "boost": "quickActions/boost",
        }
        if action not in paths:
            raise HomeAssistantError("Unsupported whole-home heating action")
        result = await self.call("POST", paths[action])
        return {
            "action": action,
            "accepted": True,
            "affected": "all_tado_heating_rooms",
            "dhw_changed": False,
            "flow_adaptation_changed_by_integration": False,
            "boost_duration_minutes": 30 if action == "boost" else None,
            "response": result if isinstance(result, dict) else {},
        }

    async def get_dhw(self):
        return await self.call("GET", "programmer/domesticHotWater/state")

    async def set_dhw(self, value: float):
        state = await self.get_dhw()
        if not isinstance(state, dict) or not isinstance(state.get("setpoint"), (int, float)):
            raise HomeAssistantError("tado X DHW setpoint is not exposed")
        limits = state.get("setpointConstraints") or {}
        low, high = limits.get("min", 35), limits.get("max", 70)
        if not math.isfinite(value) or not low <= value <= high:
            raise HomeAssistantError(f"DHW setpoint must be between {low} and {high} °C")
        await self.call("POST", "programmer/domesticHotWater/manualControl",
                        {"setpoint": value})
        return await self.get_dhw()

    async def dhw_boost(self, boost: str):
        if boost not in ("ON", "OFF"):
            raise HomeAssistantError("DHW boost must be ON or OFF")
        await self.call("POST", "programmer/domesticHotWater/boost", {"boost": boost})
        return await self.get_dhw()

    async def dhw_resume(self):
        await self.call("POST", "programmer/domesticHotWater/resumeSchedule")
        return await self.get_dhw()

    async def get_flow(self):
        return await self.call("GET", "settings/flowTemperatureOptimization")

    async def set_flow(self, *, max_temp: int | None = None,
                       enabled: bool | None = None):
        original = await self.get_flow()
        if not isinstance(original, dict):
            raise HomeAssistantError("Flow temperature optimisation is not available")
        payload: dict = {}
        if max_temp is not None:
            limits = original.get("maxFlowTemperatureConstraints") or {}
            low, high = limits.get("min", 20), limits.get("max", 75)
            if type(max_temp) is not int or not low <= max_temp <= high:
                raise HomeAssistantError(f"Maximum flow temperature must be {low}–{high} °C")
            payload["maxFlowTemperature"] = max_temp
        if enabled is not None:
            if type(enabled) is not bool:
                raise HomeAssistantError("Auto-adaptation must be true or false")
            payload["autoAdaptation"] = {"enabled": enabled}
        if not payload:
            raise HomeAssistantError("Nothing to update")
        await self.call("PATCH", "settings/flowTemperatureOptimization", payload)
        return await self.get_flow()


def _minutes(value: str, *, last: bool = False) -> int:
    if value == "24:00" and last:
        return 1440
    if not isinstance(value, str) or not TIME_RE.fullmatch(value):
        raise HomeAssistantError("Time must be HH:MM (or 24:00 for day's end)")
    h, m = (int(p) for p in value.split(":"))
    return h * 60 + m


def _canonical_block(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise HomeAssistantError("Invalid schedule block")
    setting = raw.get("setting") if isinstance(raw.get("setting"), dict) else raw
    start, end = raw.get("start"), raw.get("end", "24:00")
    start_minutes = _minutes(start)
    end_minutes = _minutes(end, last=True)
    power = setting.get("power")
    if power not in ("ON", "OFF"):
        raise HomeAssistantError("Schedule power must be ON or OFF")
    if power == "ON":
        temp = setting.get("temperature")
        temp = temp.get("value") if isinstance(temp, dict) else temp
        if type(temp) not in (int, float) or not math.isfinite(temp) or not 5 <= temp <= 30:
            raise HomeAssistantError("Heating target must be between 5 and 30 °C")
        temp = float(temp)
    else:
        temp = None
    return {"start": start_minutes, "end": end_minutes,
            "power": power, "temperature": temp}


def canonical_day(source: Any, day: str) -> list[dict]:
    """Normalise the HOPS response's flat schedule or per-day schedule."""
    if isinstance(source, dict):
        if isinstance(source.get("schedule"), list):
            source = source["schedule"]
        elif isinstance(source.get("daySchedule"), list):
            source = source["daySchedule"]
        else:
            return []
    if not isinstance(source, list):
        return []
    raw = [b for b in source if isinstance(b, dict)
           and b.get("dayType", day) == day]
    # Server omits last 'end' on some responses; fill from next block.
    raw = sorted(raw, key=lambda b: b.get("start", ""))
    for index, block in enumerate(raw):
        if "end" not in block:
            raw[index] = {**block, "end": raw[index + 1]["start"] if index + 1 < len(raw) else "24:00"}
    result = [_canonical_block(b) for b in raw]
    _validate_day(result)
    return result


def _validate_day(blocks: list[dict]) -> None:
    if not 1 <= len(blocks) <= 48:
        raise HomeAssistantError("Schedule must contain 1–48 time blocks")
    previous_end = 0
    for block in blocks:
        if block["start"] != previous_end or block["end"] <= block["start"]:
            raise HomeAssistantError("Schedule must cover 00:00–24:00 without gaps or overlaps")
        previous_end = block["end"]
    if previous_end != 1440:
        raise HomeAssistantError("Schedule must end at 24:00")


def make_day_payload(day: str, blocks: list[dict]) -> dict:
    if day not in DAYS or not isinstance(blocks, list):
        raise HomeAssistantError("Invalid schedule weekday or blocks")
    canonical = sorted([_canonical_block(b) for b in blocks], key=lambda x: x["start"])
    _validate_day(canonical)
    return {
        "dayType": day,
        "daySchedule": [
            {
                "dayType": day,
                "start": f'{b["start"] // 60:02}:{b["start"] % 60:02}',
                "end": "24:00" if b["end"] == 1440 else f'{b["end"] // 60:02}:{b["end"] % 60:02}',
                "setting": {
                    "power": b["power"],
                    **({"temperature": {"value": b["temperature"]}} if b["power"] == "ON" else {}),
                },
            }
            for b in canonical
        ],
    }


def schedule_signature(canonical: list[dict]) -> str:
    """SHA256 over a canonical single day, used solely as optimistic write token."""
    return hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()


class TadoXSettingsCoordinator(DataUpdateCoordinator):
    """Lightweight 30-minute settings cache, separate from five-minute room polls."""

    def __init__(self, hass, main):
        super().__init__(hass, _LOGGER, name="tado X DHW/flow settings",
                         update_interval=X_POLL_INTERVAL)
        self.client = TadoXClient(main)
        self.data = {"dhw": None, "flow": None}

    async def _async_update_data(self):
        snapshot = dict(self.data or {"dhw": None, "flow": None})
        try:
            snapshot["dhw"] = await self.client.get_dhw()
            snapshot["flow"] = await self.client.get_flow()
        except Exception as exc:
            raise UpdateFailed("Unable to retrieve tado X settings") from exc
        return snapshot
