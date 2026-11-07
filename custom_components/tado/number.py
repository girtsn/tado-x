"""Tado X editable hot-water and flow-temperature setpoints."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import TadoConfigEntry
from .x_entities import TadoXDhwSetpointNumber, TadoXFlowMaxNumber, TadoXRoomCapacityNumber
from .x_features import energy_enabled


async def async_setup_entry(
    hass: HomeAssistant, entry: TadoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    main = entry.runtime_data.coordinator
    if not main.is_x:
        return
    entities = []
    if main.x_settings is not None:
        entities.extend([
            TadoXDhwSetpointNumber(main.x_settings, main),
            TadoXFlowMaxNumber(main.x_settings, main),
        ])
    if energy_enabled(entry):
        # Your installed-radiator model is house-specific. Do not create
        # its per-room number entities for new users unless they opt in.
        entities.extend(TadoXRoomCapacityNumber(main, zone)
                        for zone in main.zones)
    if entities:
        async_add_entities(entities)
