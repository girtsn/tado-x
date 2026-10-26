"""Household Home/Away/Auto control for Tado."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import TadoConfigEntry
from .entity import TadoHomeEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TadoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the household-level presence selector."""
    async_add_entities([TadoPresenceSelect(entry.runtime_data.coordinator)])


class TadoPresenceSelect(TadoHomeEntity, SelectEntity):
    """Select household presence mode via the existing Tado API methods."""

    _attr_name = "Presence"
    _attr_options = ["Home", "Away", "Auto"]
    _attr_icon = "mdi:home-account"

    def __init__(self, coordinator) -> None:
        """Initialize a single selector for the Tado home."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.home_id} presence"

    @property
    def current_option(self) -> str | None:
        """Reflect the mode reported by Tado, not the last requested mode."""
        geofence = self.coordinator.data.get("geofence")
        if not isinstance(geofence, dict):
            return None
        locked = geofence.get("presenceLocked")
        if locked is False:
            return "Auto"
        if locked is not True:
            return None
        presence = geofence.get("presence")
        return {"HOME": "Home", "AWAY": "Away"}.get(presence)

    async def async_select_option(self, option: str) -> None:
        """Send the selected household mode to Tado and refresh its state."""
        if option not in self.options:
            raise ValueError(f"Unsupported Tado presence mode: {option}")
        await self.coordinator.set_presence(option.lower())
        await self.coordinator.async_request_refresh()
