"""Tado X editable hot-water and flow-temperature setpoints."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import TadoConfigEntry
from .x_entities import TadoXDhwSetpointNumber, TadoXFlowMaxNumber, TadoXRoomCapacityNumber


async def async_setup_entry(
    hass: HomeAssistant, entry: TadoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    main = entry.runtime_data.coordinator
    if not main.is_x or main.x_settings is None:
        return
    async_add_entities([
        TadoXDhwSetpointNumber(main.x_settings, main),
        TadoXFlowMaxNumber(main.x_settings, main),
        *[TadoXRoomCapacityNumber(main, zone) for zone in main.zones],
    ])
