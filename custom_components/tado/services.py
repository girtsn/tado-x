"""Services for the Tado integration."""

import logging

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import selector

from .tadox_ext import DAYS, TadoXClient, canonical_day, schedule_signature
from .heat_allocation import allocate_recent, allocation_history, diagnose_unallocated
from .radiator_inventory import radiator_capacity_report, GROUP_PHYSICAL_IDS

from .const import (
    ATTR_MESSAGE,
    CONF_CONFIG_ENTRY,
    CONF_READING,
    DOMAIN,
    SERVICE_ADD_METER_READING,
)

_LOGGER = logging.getLogger(__name__)
SCHEMA_ADD_METER_READING = vol.Schema(
    {
        vol.Required(CONF_CONFIG_ENTRY): selector.ConfigEntrySelector(
            {
                "integration": DOMAIN,
            }
        ),
        vol.Required(CONF_READING): vol.Coerce(int),
    }
)


@callback
def setup_services(hass: HomeAssistant) -> None:
    """Set up the services for the Tado integration."""

    async def add_meter_reading(call: ServiceCall) -> None:
        """Send meter reading to Tado."""
        entry_id: str = call.data[CONF_CONFIG_ENTRY]
        reading: int = call.data[CONF_READING]
        _LOGGER.debug("Add meter reading %s", reading)

        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None:
            raise ServiceValidationError("Config entry not found")

        coordinator = entry.runtime_data.coordinator
        response: dict = await coordinator.set_meter_reading(call.data[CONF_READING])

        if ATTR_MESSAGE in response:
            raise HomeAssistantError(response[ATTR_MESSAGE])

    hass.services.async_register(
        DOMAIN, SERVICE_ADD_METER_READING, add_meter_reading, SCHEMA_ADD_METER_READING
    )

    # tado X services live in the existing 'tado' domain so there is no second
    # integration, login, or separate set of device entities.
    def get_x_coordinator(call: ServiceCall):
        selected = call.data.get("config_entry")
        entries = [e for e in hass.config_entries.async_entries(DOMAIN)
                   if getattr(getattr(e, "runtime_data", None), "coordinator", None)
                   and e.runtime_data.coordinator.is_x]
        if selected:
            entries = [e for e in entries if e.entry_id == selected]
        if len(entries) != 1:
            raise ServiceValidationError(
                "Select one loaded tado X home via config_entry"
            )
        return entries[0].runtime_data.coordinator

    async def list_x_rooms(call: ServiceCall) -> dict:
        coord = get_x_coordinator(call)
        return {
            "home": coord.home_name,
            "config_entry": coord.config_entry.entry_id,
            "rooms": [{"room_id": int(z["id"]), "name": z["name"]}
                      for z in coord.zones if "id" in z and "name" in z],
        }

    async def get_x_schedule(call: ServiceCall) -> dict:
        coord = get_x_coordinator(call)
        room_id = call.data["room_id"]
        api = TadoXClient(coord)
        raw = await api.get_schedule(room_id)
        if raw is None:
            raise HomeAssistantError("Room schedule unavailable (HTTP 404)")
        days = {}
        for day in DAYS:
            blocks = canonical_day(raw, day)
            days[day] = {"blocks": [
                {"start": f'{b["start"]//60:02}:{b["start"]%60:02}',
                 "end": "24:00" if b["end"] == 1440
                        else f'{b["end"]//60:02}:{b["end"]%60:02}',
                 "power": b["power"], "temperature": b["temperature"]}
                for b in blocks
            ], "signature": schedule_signature(blocks)}
        return {"room_id": room_id, "days": days}

    async def save_x_day(call: ServiceCall) -> dict:
        coord = get_x_coordinator(call)
        api = TadoXClient(coord)
        result = await api.save_day(
            call.data["room_id"], call.data["day"],
            call.data["blocks"], call.data["expected_signature"],
        )
        return result

    async def x_get_settings(call: ServiceCall) -> dict:
        coord = get_x_coordinator(call)
        settings = getattr(coord, "x_settings", None)
        if settings is None:
            raise HomeAssistantError("tado X settings coordinator not loaded")
        # Force refresh only when user explicitly requests this response.
        await settings.async_request_refresh()
        state = settings.data or {}
        return {"dhw": state.get("dhw"), "flow": state.get("flow")}

    async def x_set_dhw(call: ServiceCall) -> dict:
        coord = get_x_coordinator(call)
        result = await TadoXClient(coord).set_dhw(float(call.data["temperature"]))
        if coord.x_settings:
            await coord.x_settings.async_request_refresh()
        return {"state": result}

    async def x_boost_dhw(call: ServiceCall) -> dict:
        coord = get_x_coordinator(call)
        result = await TadoXClient(coord).dhw_boost(call.data["boost"])
        if coord.x_settings:
            await coord.x_settings.async_request_refresh()
        return {"state": result}

    async def x_resume_dhw(call: ServiceCall) -> dict:
        coord = get_x_coordinator(call)
        result = await TadoXClient(coord).dhw_resume()
        if coord.x_settings:
            await coord.x_settings.async_request_refresh()
        return {"state": result}

    async def x_set_flow(call: ServiceCall) -> dict:
        coord = get_x_coordinator(call)
        if "max_temperature" not in call.data and "auto_adaptation" not in call.data:
            raise ServiceValidationError("Specify max_temperature and/or auto_adaptation")
        result = await TadoXClient(coord).set_flow(
            max_temp=call.data.get("max_temperature"),
            enabled=call.data.get("auto_adaptation"),
        )
        if coord.x_settings:
            await coord.x_settings.async_request_refresh()
        return {"settings": result}

    home = {vol.Optional("config_entry"): str}
    room = {**home, vol.Required("room_id"): vol.All(vol.Coerce(int), vol.Range(min=1))}
    hass.services.async_register(
        DOMAIN, "x_list_rooms", list_x_rooms,
        schema=vol.Schema(home), supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, "x_get_schedule", get_x_schedule,
        schema=vol.Schema(room), supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, "x_save_day", save_x_day,
        schema=vol.Schema({**room,
            vol.Required("day"): vol.In(DAYS),
            vol.Required("blocks"): [dict],
            vol.Required("expected_signature"): vol.Match(r"^[0-9a-f]{64}$"),
        }), supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, "x_get_settings", x_get_settings,
        schema=vol.Schema(home), supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, "x_set_dhw_temperature", x_set_dhw,
        schema=vol.Schema({**home, vol.Required("temperature"):
                           vol.All(vol.Coerce(float), vol.Range(min=35, max=70))}),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, "x_boost_dhw", x_boost_dhw,
        schema=vol.Schema({**home, vol.Required("boost"): vol.In(("ON", "OFF"))}),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, "x_resume_dhw", x_resume_dhw,
        schema=vol.Schema(home), supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, "x_set_flow", x_set_flow,
        schema=vol.Schema({**home,
            vol.Optional("max_temperature"): vol.All(vol.Coerce(int),
                                                     vol.Range(min=20, max=75)),
            vol.Optional("auto_adaptation"): bool,
        }), supports_response=SupportsResponse.OPTIONAL,
    )

    async def x_compute_estimates(call: ServiceCall) -> dict:
        main = get_x_coordinator(call)
        async with main.x_allocation_lock:
            return await allocate_recent(
                hass, main, days=call.data.get("days", 3),
                dry_run=call.data.get("dry_run", False),
            )

    async def x_estimate_history(call: ServiceCall) -> dict:
        main = get_x_coordinator(call)
        return await allocation_history(
            hass, main, period=call.data.get("period", "month")
        )

    hass.services.async_register(
        DOMAIN, "x_compute_heating_allocation", x_compute_estimates,
        schema=vol.Schema({**home,
            vol.Optional("days", default=3): vol.All(vol.Coerce(int), vol.Range(min=1, max=35)),
            vol.Optional("dry_run", default=False): bool,
        }), supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, "x_heating_allocation_history", x_estimate_history,
        schema=vol.Schema({**home, vol.Optional("period", default="month"):
                           vol.In(["day", "week", "month", "year", "3years"])}),
        supports_response=SupportsResponse.ONLY,
    )

    async def x_diagnose_unallocated(call: ServiceCall) -> dict:
        """Read-only local Recorder diagnostic, never changing estimates."""
        main = get_x_coordinator(call)
        return await diagnose_unallocated(
            hass, main, days=call.data.get("days", 35),
            limit=call.data.get("limit", 30),
        )

    hass.services.async_register(
        DOMAIN, "x_diagnose_unallocated_heating", x_diagnose_unallocated,
        schema=vol.Schema({
            **home,
            vol.Optional("days", default=35): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=35)
            ),
            vol.Optional("limit", default=30): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=100)
            ),
        }), supports_response=SupportsResponse.ONLY,
    )

    async def x_radiator_capacities(call: ServiceCall) -> dict:
        """Show current tado room-to-physical-radiator mapping and rated W."""
        main = get_x_coordinator(call)
        return radiator_capacity_report(
            main.zones, main.config_entry.options.get("x_capacity_kw", {}),
            main.config_entry.options.get("x_radiator_room_mapping", {}),
        )

    async def x_apply_radiator_capacities(call: ServiceCall) -> dict:
        """Persist only safely matched nominal capacities; never write tado."""
        main = get_x_coordinator(call)
        report = radiator_capacity_report(
            main.zones, main.config_entry.options.get("x_capacity_kw", {}),
            main.config_entry.options.get("x_radiator_room_mapping", {}),
        )
        entry = main.config_entry
        values = dict(entry.options.get("x_capacity_kw", {}))
        overwrite = call.data.get("overwrite_existing", False)
        dry_run = call.data.get("dry_run", True)
        updates = []
        skipped = []
        for room in report["rooms"]:
            if room["status"] != "matched":
                skipped.append({"room": room["room"], "reason": room["status"]})
                continue
            rid = str(room["room_id"])
            if not overwrite and rid in values:
                skipped.append({"room": room["room"], "reason": "existing_manual_override_preserved"})
                continue
            value = round(float(room["rated_w"]) / 1000, 3)
            values[rid] = value
            updates.append({"room": room["room"], "room_id": room["room_id"], "kw": value})
        if not dry_run and updates:
            main.hass.config_entries.async_update_entry(
                entry, options={**entry.options, "x_capacity_kw": values}
            )
            main.async_update_listeners()
        return {
            "status": "preview_only" if dry_run else "applied_locally",
            "updated_rooms": updates,
            "skipped_rooms": skipped,
            "radiator_heating_settings_changed": False,
            "boiler_settings_changed": False,
            "source_statistics_modified": False,
        }

    hass.services.async_register(
        DOMAIN, "x_radiator_capacity_report", x_radiator_capacities,
        schema=vol.Schema(home), supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, "x_apply_radiator_capacities", x_apply_radiator_capacities,
        schema=vol.Schema({
            **home,
            vol.Optional("dry_run", default=True): bool,
            vol.Optional("overwrite_existing", default=False): bool,
        }), supports_response=SupportsResponse.OPTIONAL,
    )

    async def x_assign_radiator_room(call: ServiceCall) -> dict:
        """Bind a named physical-room inventory group to one real tado room ID.

        This changes only Home Assistant's local estimate metadata; it does NOT
        change tado cloud schedules, devices, radiator valves or boiler flow.
        """
        main = get_x_coordinator(call)
        room_id = str(call.data["room_id"])
        if room_id not in {str(z["id"]) for z in main.zones}:
            raise ServiceValidationError("Unknown tado room_id; call tado.x_list_rooms")
        requested = call.data["physical_room"]
        if requested != "auto" and requested not in GROUP_PHYSICAL_IDS:
            raise ServiceValidationError("Unknown physical radiator room")
        current = dict(main.config_entry.options.get("x_radiator_room_mapping", {}))
        if requested == "auto":
            current.pop(room_id, None)
        else:
            if any(other_id != room_id and group == requested
                   for other_id, group in current.items()):
                raise ServiceValidationError("That radiator room is assigned to another tado room")
            current[room_id] = requested
        main.hass.config_entries.async_update_entry(
            main.config_entry,
            options={**main.config_entry.options,
                     "x_radiator_room_mapping": current},
        )
        main.async_update_listeners()
        return {
            "status": "mapped_locally",
            "tado_room_id": int(room_id),
            "physical_room": requested,
            "radiator_ids": GROUP_PHYSICAL_IDS.get(requested, []),
            "boiler_settings_changed": False,
            "tado_settings_changed": False,
        }

    hass.services.async_register(
        DOMAIN, "x_assign_radiator_room", x_assign_radiator_room,
        schema=vol.Schema({
            **home,
            vol.Required("room_id"): vol.All(vol.Coerce(int), vol.Range(min=1)),
            vol.Required("physical_room"): vol.In(["auto", *GROUP_PHYSICAL_IDS]),
        }), supports_response=SupportsResponse.OPTIONAL,
    )
