"""Support for Tado sensors for each zone."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.const import EntityCategory
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from . import TadoConfigEntry
from .const import (
    TADO_LINE_X,
    TADO_PRE_LINE_X,
    TYPE_AIR_CONDITIONING,
    TYPE_BATTERY,
    TYPE_HEATING,
    TYPE_HOT_WATER,
    TYPE_POWER,
)
from .coordinator import TadoDataUpdateCoordinator
from .entity import TadoDeviceEntity, TadoZoneEntity, TadoHomeEntity
from .x_features import energy_enabled

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class TadoBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes Tado binary sensor entity."""

    state_fn: Callable[[Any], bool]

    attributes_fn: Callable[[Any], dict[Any, StateType]] | None = None


BATTERY_STATE_ENTITY_DESCRIPTION = TadoBinarySensorEntityDescription(
    key="battery state",
    state_fn=lambda data: data["batteryState"] == "LOW",
    device_class=BinarySensorDeviceClass.BATTERY,
)
CONNECTION_STATE_ENTITY_DESCRIPTION = TadoBinarySensorEntityDescription(
    key="connection state",
    translation_key="connection_state",
    state_fn=lambda data: data.get("connectionState", {}).get("value", False),
    device_class=BinarySensorDeviceClass.CONNECTIVITY,
)
TADO_X_CONNECTION_STATE_ENTITY_DESCRIPTION = TadoBinarySensorEntityDescription(
    key="connection state",
    translation_key="connection_state",
    state_fn=lambda data: data.get("connection", {}).get("state") == "CONNECTED",
    device_class=BinarySensorDeviceClass.CONNECTIVITY,
)
POWER_ENTITY_DESCRIPTION = TadoBinarySensorEntityDescription(
    key="power",
    state_fn=lambda data: data.power == "ON",
    device_class=BinarySensorDeviceClass.POWER,
)
LINK_ENTITY_DESCRIPTION = TadoBinarySensorEntityDescription(
    key="link",
    state_fn=lambda data: data.link in ("ONLINE", "CONNECTED"),
    device_class=BinarySensorDeviceClass.CONNECTIVITY,
)
OVERLAY_ENTITY_DESCRIPTION = TadoBinarySensorEntityDescription(
    key="overlay",
    translation_key="overlay",
    state_fn=lambda data: data.overlay_active,
    attributes_fn=lambda data: (
        {"termination": data.overlay_termination_type} if data.overlay_active else {}
    ),
    device_class=BinarySensorDeviceClass.POWER,
)
OPEN_WINDOW_ENTITY_DESCRIPTION = TadoBinarySensorEntityDescription(
    key="open window",
    state_fn=lambda data: bool(data.open_window or data.open_window_detected),
    attributes_fn=lambda data: data.open_window_attr,
    device_class=BinarySensorDeviceClass.WINDOW,
)
EARLY_START_ENTITY_DESCRIPTION = TadoBinarySensorEntityDescription(
    key="early start",
    translation_key="early_start",
    state_fn=lambda data: data.preparation,
    device_class=BinarySensorDeviceClass.POWER,
)

DEVICE_SENSORS = {
    TADO_LINE_X: {
        TYPE_BATTERY: [
            BATTERY_STATE_ENTITY_DESCRIPTION,
            TADO_X_CONNECTION_STATE_ENTITY_DESCRIPTION,
        ],
        TYPE_POWER: [
            TADO_X_CONNECTION_STATE_ENTITY_DESCRIPTION,
        ],
    },
    TADO_PRE_LINE_X: {
        TYPE_BATTERY: [
            BATTERY_STATE_ENTITY_DESCRIPTION,
            CONNECTION_STATE_ENTITY_DESCRIPTION,
        ],
        TYPE_POWER: [
            CONNECTION_STATE_ENTITY_DESCRIPTION,
        ],
    },
}

ZONE_SENSORS = {
    TADO_LINE_X: {
        TYPE_HEATING: [
            POWER_ENTITY_DESCRIPTION,
            LINK_ENTITY_DESCRIPTION,
            OVERLAY_ENTITY_DESCRIPTION,
            OPEN_WINDOW_ENTITY_DESCRIPTION,
        ],
        TYPE_HOT_WATER: [
            POWER_ENTITY_DESCRIPTION,
            LINK_ENTITY_DESCRIPTION,
            OVERLAY_ENTITY_DESCRIPTION,
        ],
    },
    TADO_PRE_LINE_X: {
        TYPE_HEATING: [
            POWER_ENTITY_DESCRIPTION,
            LINK_ENTITY_DESCRIPTION,
            OVERLAY_ENTITY_DESCRIPTION,
            OPEN_WINDOW_ENTITY_DESCRIPTION,
            EARLY_START_ENTITY_DESCRIPTION,
        ],
        TYPE_AIR_CONDITIONING: [
            POWER_ENTITY_DESCRIPTION,
            LINK_ENTITY_DESCRIPTION,
            OVERLAY_ENTITY_DESCRIPTION,
            OPEN_WINDOW_ENTITY_DESCRIPTION,
        ],
        TYPE_HOT_WATER: [
            POWER_ENTITY_DESCRIPTION,
            LINK_ENTITY_DESCRIPTION,
            OVERLAY_ENTITY_DESCRIPTION,
        ],
    },
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TadoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Tado sensor platform."""

    tado = entry.runtime_data.coordinator
    devices = tado.devices
    zones = tado.zones
    entities: list[BinarySensorEntity] = []
    tado_line = TADO_LINE_X if tado.is_x else TADO_PRE_LINE_X

    # Restore previously registered battery sensors even if the API omits
    # batteryState during this startup. Preserve their existing unique IDs.
    registry = er.async_get(hass)
    for device in devices:
        device_id = device["serialNumber"] if device["is_x"] else device["shortSerialNo"]
        battery_unique_id = f"{BATTERY_STATE_ENTITY_DESCRIPTION.key} {device_id} {tado.home_id}"
        known_battery = registry.async_get_entity_id(
            "binary_sensor", "tado", battery_unique_id
        ) is not None
        if "batteryState" in device or known_battery:
            device_type = TYPE_BATTERY
        else:
            device_type = TYPE_POWER

        entities.extend(
            [
                TadoDeviceBinarySensor(tado, device, entity_description)
                for entity_description in DEVICE_SENSORS[tado_line][device_type]
            ]
        )

    # Create zone sensors
    for zone in zones:
        zone_type = zone["type"]
        if zone_type not in ZONE_SENSORS[tado_line]:
            _LOGGER.warning(
                "Unknown or unsupported zone type skipped: %s, tado line: %s",
                zone_type,
                tado_line,
            )
            continue

        entities.extend(
            [
                TadoZoneBinarySensor(tado, zone["name"], zone["id"], entity_description)
                for entity_description in ZONE_SENSORS[tado_line][zone_type]
            ]
        )

    if tado.is_x:
        # Always publish a read-only state of the one optional integration
        # feature. Lovelace's section visibility cannot read config entry
        # options directly; it CAN read this binary sensor. This is not a
        # configuration switch and never changes the option.
        entities.append(TadoXVaillantEnergyEnabledBinarySensor(tado, entry))
        entities.extend([
            TadoXCloudConnectionBinarySensor(tado, "main_api"),
            TadoXCloudConnectionBinarySensor(tado, "settings_api"),
        ])
    async_add_entities(entities, True)



class TadoXCloudConnectionBinarySensor(TadoHomeEntity, BinarySensorEntity):
    """Cloud health stays available even when the coordinator is offline.

    A local 60-second watchdog catches stalled polling without extra API calls.
    These flags describe tado cloud access, not individual radiator radio links.
    """

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, main, scope: str):
        super().__init__(main)
        self._scope = scope
        self._source = main if scope == "main_api" else main.x_settings
        self._attr_unique_id = f"{main.home_id}_x_{scope}_cloud_connection_state"
        if scope == "main_api":
            self._attr_name = "tado X API cloud connection state"
            self.entity_id = "binary_sensor.tado_x_api_cloud_connection_state"
            self._max_age = timedelta(minutes=15)
        else:
            self._attr_name = "tado X settings cloud connection state"
            self.entity_id = "binary_sensor.tado_x_settings_cloud_connection_state"
            self._max_age = timedelta(minutes=95)

    @property
    def available(self) -> bool:
        """Remain readable on a failed or timed-out API poll."""
        return True

    @property
    def is_on(self) -> bool:
        source = self._source
        updated = source.last_successful_update if source else None
        return bool(
            source and source.last_update_success and updated is not None
            and timedelta(0) <= datetime.now(timezone.utc) - updated < self._max_age
        )

    @property
    def extra_state_attributes(self) -> dict:
        source = self._source
        updated = source.last_successful_update if source else None
        stale = updated is None or datetime.now(timezone.utc) - updated >= self._max_age
        if source is None:
            reason = "Settings coordinator not initialized"
        elif not source.last_update_success:
            reason = source.last_failure_reason or "Most recent API poll failed"
        elif stale:
            reason = "No successful API poll within the expected interval"
        else:
            reason = None
        return {
            "connectivity_scope": self._scope,
            "tado_home_id": str(self.coordinator.home_id),
            "read_only": True,
            "failure_reason": reason,
            "last_successful_update": updated.isoformat() if updated else None,
            "stale_timeout_minutes": int(self._max_age.total_seconds() // 60),
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self._source is not None and self._source is not self.coordinator:
            self.async_on_remove(
                self._source.async_add_listener(self._handle_coordinator_update)
            )

        @callback
        def refresh_watchdog(now) -> None:
            self.async_write_ha_state()

        self.async_on_remove(
            async_track_time_interval(self.hass, refresh_watchdog, timedelta(minutes=1))
        )


class TadoXVaillantEnergyEnabledBinarySensor(TadoHomeEntity, BinarySensorEntity):
    """Whether optional household Vaillant gas allocation is configured.

    Stable suggested entity ID allows one reusable dashboard YAML for the
    common single-tado-X-home installation. HA may suffix or override the ID
    for users with multiple homes or existing entity registry customizations.
    """

    _attr_name = "tado X Vaillant household energy enabled"
    _attr_icon = "mdi:chart-areaspline"
    _attr_entity_category = None

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.home_id}_x_vaillant_energy_enabled"
        self.entity_id = "binary_sensor.tado_x_vaillant_energy_enabled"
        self._attr_is_on = energy_enabled(entry)

    @property
    def extra_state_attributes(self):
        return {
            "feature": "household_vaillant_mypyllant_gas_allocation",
            "read_only": True,
            "enabled_from": "tado_integration_options",
            "general_tado_x_controls_always_enabled": True,
            "tado_home_id": str(self.coordinator.home_id),
        }


class TadoDeviceBinarySensor(TadoDeviceEntity, BinarySensorEntity):
    """Representation of a tado Sensor."""

    entity_description: TadoBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: TadoDataUpdateCoordinator,
        device_info: dict[str, Any],
        entity_description: TadoBinarySensorEntityDescription,
    ) -> None:
        """Initialize of the Tado Sensor."""
        self.entity_description = entity_description
        super().__init__(device_info, coordinator)

        self._attr_unique_id = (
            f"{entity_description.key} {self.device_id} {coordinator.home_id}"
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        try:
            self._device_info = self.coordinator.data["device"][self.device_id]
        except KeyError:
            if self.entity_description.key == BATTERY_STATE_ENTITY_DESCRIPTION.key:
                self._attr_available = False
                super()._handle_coordinator_update()
            return

        if self.entity_description.key == BATTERY_STATE_ENTITY_DESCRIPTION.key:
            # Missing/unknown battery status must not be interpreted as OK.
            battery_state = self._device_info.get("batteryState")
            self._attr_available = battery_state in ("LOW", "NORMAL")
            self._attr_is_on = battery_state == "LOW" if self._attr_available else None
        else:
            self._attr_is_on = self.entity_description.state_fn(self._device_info)
        if self.entity_description.attributes_fn is not None:
            self._attr_extra_state_attributes = self.entity_description.attributes_fn(
                self._device_info
            )
        super()._handle_coordinator_update()


class TadoZoneBinarySensor(TadoZoneEntity, BinarySensorEntity):
    """Representation of a tado Sensor."""

    entity_description: TadoBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: TadoDataUpdateCoordinator,
        zone_name: str,
        zone_id: int,
        entity_description: TadoBinarySensorEntityDescription,
    ) -> None:
        """Initialize of the Tado Sensor."""
        self.entity_description = entity_description
        super().__init__(zone_name, coordinator.home_id, zone_id, coordinator)

        self._attr_unique_id = (
            f"{entity_description.key} {zone_id} {coordinator.home_id}"
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        try:
            tado_zone_data = self.coordinator.data["zone"][self.zone_id]
        except KeyError:
            return

        self._attr_is_on = self.entity_description.state_fn(tado_zone_data)
        if self.entity_description.attributes_fn is not None:
            self._attr_extra_state_attributes = self.entity_description.attributes_fn(
                tado_zone_data
            )
        super()._handle_coordinator_update()
