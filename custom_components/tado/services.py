"""Services for the Tado integration."""

import logging

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import selector

from .tadox_ext import DAYS, TadoXClient, canonical_day, schedule_signature

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
