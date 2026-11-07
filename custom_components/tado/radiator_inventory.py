"""Installed radiator inventory with EN442 rated output at 75/65/20 °C.

The IDs R01–R11 identify PHYSICAL radiators, not tado room identifiers.
The independent room-name mapping deliberately refuses ambiguous matches.
Manual HA number-entity overrides always take precedence.

Sources:
- Desco UNI.8 product catalogue: https://www.desco.be/nl-be/producten/
- Brugman Compact 4 table: https://brugman.eu/files/downloads/Brugman-Prijslijst-FR-2025-NOUVEAU-17-10-2025.pdf
75/65/20 rating is a nominal capacity at Delta-T50, not continuously
delivered heat under tado's lower-water-temperature optimisation.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
import re
import unicodedata
from typing import Any

from homeassistant.exceptions import HomeAssistantError


@dataclass(frozen=True)
class Radiator:
    physical_id: str
    floor: str
    room: str
    series: str
    radiator_type: str
    height_mm: int
    length_mm: int
    rated_output_w: int
    inferred: bool = False


RADIATORS = (
    Radiator("R01", "0fl", "Living room", "Uni.8", "T33", 300, 3000, 3993),
    Radiator("R02", "0fl", "Entrance hallway", "Uni.8", "T33", 900, 500, 1643),
    Radiator("R03", "0fl", "Kitchen", "Uni.8", "T33", 500, 1000, 2075),
    Radiator("R04", "0fl", "Toilet", "Uni.8 SP-08", "T21", 900, 400, 721),
    Radiator("R05", "1fl", "Yard-side bedroom", "Compact 4", "T33", 500, 1200, 2424),
    Radiator("R06", "1fl", "Street-side bedroom", "Compact 4", "T33", 500, 1200, 2424),
    Radiator("R07", "1fl", "Small bedroom (yard-side)", "Compact 4", "T22", 500, 1000, 1449),
    Radiator("R08", "1fl", "Bathroom", "Compact 4", "T33", 500, 600, 1212),
    Radiator("R09", "2fl", "Attic bedroom", "Uni.8 SP-08", "T33", 700, 1200, 3269),
    Radiator("R10", "2fl", "Attic bedroom", "Uni.8 SP-08", "T33", 700, 1200, 3269),
    # Carried forward from the user's original list, missing in the R01–R10
    # correction. Explicitly marked, never presented as newly confirmed.
    Radiator("R11", "2fl", "Attic bathroom", "Uni.8 SP-08", "T33", 700, 1200, 3269, True),
)

RATING = "EN442 75/65/20 °C (Delta-T50)"
DESCO_SOURCE = "https://www.desco.be/nl-be/producten/info/d-radiator-uni8-33-h300-l3000-3993w?qpid=156524"
BRUGMAN_SOURCE = "https://brugman.eu/files/downloads/Brugman-Prijslijst-FR-2025-NOUVEAU-17-10-2025.pdf"

# Only name combinations that uniquely identify one of the ten radiator rooms.
# No generic 'bedroom' or 'bathroom': those occur on multiple floors.
ALIASES: dict[str, tuple[str, ...]] = {
    "living": ("0fl living room", "living room", "livingroom", "ground floor living room",
               "0fl living", "salon"),
    "entrance": ("0fl entrance hallway", "0fl entrance", "entrance hallway",
                 "0fl hall", "entrance", "hallway", "ground floor hallway"),
    "kitchen": ("0fl kitchen", "kitchen", "ground floor kitchen"),
    "toilet": ("0fl toilet", "toilet", "wc", "0fl wc", "guest toilet", "ground floor toilet"),
    "yard_bedroom": ("1fl yard side bedroom", "1fl bedroom yard side",
                     "yard side bedroom", "yard bedroom", "garden bedroom",
                     "1fl garden bedroom", "1fl bedroom garden side"),
    "street_bedroom": ("1fl street side bedroom", "1fl bedroom street side",
                       "street side bedroom", "street bedroom", "1fl street bedroom"),
    "small_bedroom": ("1fl small bedroom yard side", "1fl small bedroom",
                      "small bedroom", "small bedroom yard side", "1fl small bed"),
    "bathroom_1fl": ("1fl bathroom", "first floor bathroom", "1st floor bathroom",
                     "1fl bath"),
    "attic_bedroom": ("2fl attic bedroom", "attic bedroom", "2fl bedroom",
                      "second floor bedroom", "2nd floor bedroom",
                      "2fl parents bedroom", "2fl master bedroom"),
    "attic_bathroom": ("2fl attic bathroom", "attic bathroom", "2fl bathroom",
                       "second floor bathroom", "2nd floor bathroom",
                       "2fl bath"),
}
GROUP_PHYSICAL_IDS: dict[str, tuple[str, ...]] = {
    "living": ("R01",),
    "entrance": ("R02",),
    "kitchen": ("R03",),
    "toilet": ("R04",),
    "yard_bedroom": ("R05",),
    "street_bedroom": ("R06",),
    "small_bedroom": ("R07",),
    "bathroom_1fl": ("R08",),
    "attic_bedroom": ("R09", "R10"),
    "attic_bathroom": ("R11",),
}
BY_PHYSICAL_ID = {r.physical_id: r for r in RADIATORS}


def normalize_name(name: str) -> str:
    """Make case, unicode and punctuation irrelevant, not room floors."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return " ".join(re.findall(r"[a-z0-9]+", ascii_name.casefold()))


ALIAS_GROUPS: dict[str, set[str]] = {}
for key, variants in ALIASES.items():
    for alias in variants:
        ALIAS_GROUPS.setdefault(normalize_name(alias), set()).add(key)


def _get_room_group(name: str) -> str | None:
    groups = ALIAS_GROUPS.get(normalize_name(name), set())
    return next(iter(groups)) if len(groups) == 1 else None


def _room_valve_count(zone: dict[str, Any]) -> int | None:
    devices = zone.get("devices")
    if not isinstance(devices, list):
        return None
    return sum(
        1 for d in devices
        if isinstance(d, dict) and str(d.get("type", d.get("deviceType", ""))).startswith("VA")
    )


def radiator_capacity_report(zones: list[dict[str, Any]],
                             overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Report conservative tado-room-to-physical-radiator matches.

    Only unambiguous exact aliases are auto-mapped. If two HA rooms match a
    single physical group, neither is auto-mapped. A mismatch of valve counts
    is reported, never silently equated with physical heat output.
    """
    overrides = overrides if isinstance(overrides, dict) else {}
    matched = [_get_room_group(str(z.get("name", ""))) for z in zones]
    counts = Counter(group for group in matched if group is not None)
    output: list[dict[str, Any]] = []
    total_rated_w = 0
    mapped_rated_w = 0
    for zone, group in zip(zones, matched, strict=True):
        name = str(zone.get("name", ""))
        zid = str(zone["id"])
        physical = [BY_PHYSICAL_ID[pid] for pid in GROUP_PHYSICAL_IDS[group]] if group else []
        ambiguous = group is not None and counts[group] != 1
        if ambiguous:
            physical = []
        rated_w = sum(r.rated_output_w for r in physical)
        valve_count = _room_valve_count(zone)
        expected = len(physical) if physical else None
        status = (
            "ambiguous_multiple_tado_zones" if ambiguous
            else "unmatched_needs_manual_wattage" if not physical
            else "valve_count_mismatch_review" if valve_count is not None and valve_count != expected
            else "matched_inferred_r11" if any(r.inferred for r in physical)
            else "matched"
        )
        overridden = overrides.get(zid)
        manual_kw = float(overridden) if type(overridden) in (int, float) and math.isfinite(overridden) and overridden > 0 else None
        # Only a positive, unique group match is used as a rated-output
        # default; mismatched valve counts require a user review.
        inferred_kw = round(rated_w / 1000, 3) if status in ("matched", "matched_inferred_r11") else None
        default_kw = inferred_kw
        effective_kw = manual_kw if manual_kw is not None else default_kw
        output.append({
            "room_id": int(zone["id"]), "room": name,
            "status": status, "source": "manual_override" if manual_kw is not None else (
                "installed_radiator_inventory" if default_kw is not None else "unset"),
            "radiator_ids": [r.physical_id for r in physical],
            "radiators": [{"id": r.physical_id,
                           "series": r.series, "type": r.radiator_type,
                           "height_mm": r.height_mm, "length_mm": r.length_mm,
                           "rated_w": r.rated_output_w, "inferred": r.inferred}
                          for r in physical],
            "rated_w": rated_w if physical else None,
            "capacity_kw": effective_kw,
            "manual_override_kw": manual_kw,
            "expected_radiators": expected,
            "tado_radiator_valves": valve_count,
        })
        total_rated_w += rated_w
        if default_kw is not None:
            mapped_rated_w += rated_w
    return {
        "rating": RATING,
        "total_inventory_w": sum(r.rated_output_w for r in RADIATORS),
        "includes_inferred_r11": True,
        "matched_rated_w": mapped_rated_w,
        "matched_rooms": sum(row["capacity_kw"] is not None for row in output),
        "rooms": output,
        "note": "Nominal output at 75/65/20; relative heating allocation weights only. Unmatched rooms require a manually entered capacity. R11 came from the earlier inventory and remains unconfirmed.",
    }


def require_valid_capacities(zones: list[dict[str, Any]],
                             overrides: dict[str, Any] | None = None) -> dict[str, float]:
    """Never replace an unknown radiator with a fabricated 1 kW weight."""
    report = radiator_capacity_report(zones, overrides)
    missing = [r["room"] for r in report["rooms"] if r["capacity_kw"] is None]
    if missing:
        raise HomeAssistantError(
            "Radiator rated output needs review for: " + ", ".join(missing)
            + ". Set the per-room number entities or use the capacity preview."
        )
    return {str(r["room_id"]): r["capacity_kw"] for r in report["rooms"]}
