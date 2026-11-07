"""Household Home/Away/Auto control for Tado."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import TadoConfigEntry
from .entity import TadoHomeEntity
from .presence_mode import effective_presence, selected_presence_mode


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TadoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the household-level presence selector."""
    main = entry.runtime_data.coordinator
    entities = [TadoPresenceSelect(main)]
    async_add_entities(entities)


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
        return selected_presence_mode(self.coordinator.data.get("geofence"))

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        """Expose both control mode and observed presence to HA diagnostics."""
        return {
            "tado_home_id": str(self.coordinator.home_id),
            "presence_scope": "selected",
            "effective_presence": effective_presence(
                self.coordinator.data.get("geofence")
            ),
        }

    async def async_select_option(self, option: str) -> None:
        """Send the selected household mode to Tado and refresh its state."""
        if option not in self.options:
            raise ValueError(f"Unsupported Tado presence mode: {option}")
        await self.coordinator.set_presence(option.lower())
        await self.coordinator.async_request_refresh()
