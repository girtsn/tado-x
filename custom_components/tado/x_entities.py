"""Home Assistant entities for optional tado X DHW and flow configuration."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.components.switch import SwitchEntity
from homeassistant.components.select import SelectEntity
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .tadox_ext import TadoXClient
from .entity import TadoZoneEntity
from .heat_allocation import _capacities


class TadoXSettingsEntity(CoordinatorEntity):
    """A home-level tado X settings entity backed by the 30-minute cache."""

    _attr_has_entity_name = True

    def __init__(self, settings, main, suffix: str):
        super().__init__(settings)
        self._main = main
        self._attr_unique_id = f"{main.home_id}_x_{suffix}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(main.home_id))},
            name=main.home_name,
            manufacturer="tado",
            model="tado X home",
        )

    def _item(self, path: str):
        value = (self.coordinator.data or {})
        for part in path.split("."):
            if not isinstance(value, dict):
                return None
            value = value.get(part)
        return value


class TadoXDhwSetpointNumber(TadoXSettingsEntity, NumberEntity):
    """Tado X hot-water setpoint; writes use the HOPS manualControl endpoint."""

    _attr_name = "DHW target temperature"
    _attr_icon = "mdi:water-thermometer"
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_mode = NumberMode.BOX
    _attr_native_step = 1

    def __init__(self, settings, main):
        super().__init__(settings, main, "dhw_setpoint")

    @property
    def available(self):
        return super().available and self._item("dhw.setpoint") is not None

    @property
    def native_value(self):
        return self._item("dhw.setpoint")

    @property
    def native_min_value(self):
        return self._item("dhw.setpointConstraints.min") or 35

    @property
    def native_max_value(self):
        return self._item("dhw.setpointConstraints.max") or 70

    async def async_set_native_value(self, value: float):
        await TadoXClient(self._main).set_dhw(value)
        await self.coordinator.async_request_refresh()


class TadoXFlowMaxNumber(TadoXSettingsEntity, NumberEntity):
    """Max flow-temperature slider sent to tado optimisation."""

    _attr_name = "Maximum heating flow temperature"
    _attr_icon = "mdi:heating-coil"
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    def __init__(self, settings, main):
        super().__init__(settings, main, "flow_max_temperature")

    @property
    def available(self):
        return super().available and self._item("flow.maxFlowTemperature") is not None

    @property
    def native_value(self):
        return self._item("flow.maxFlowTemperature")

    @property
    def native_min_value(self):
        return self._item("flow.maxFlowTemperatureConstraints.min") or 20

    @property
    def native_max_value(self):
        return self._item("flow.maxFlowTemperatureConstraints.max") or 75

    async def async_set_native_value(self, value: float):
        await TadoXClient(self._main).set_flow(max_temp=int(value))
        await self.coordinator.async_request_refresh()


class TadoXAutoAdaptationSwitch(TadoXSettingsEntity, SwitchEntity):
    """Enable or disable tado's automatic flow-temperature adaptation."""

    _attr_name = "Automatic flow temperature adaptation"
    _attr_icon = "mdi:thermometer-auto"

    def __init__(self, settings, main):
        super().__init__(settings, main, "flow_auto_adaptation")

    @property
    def available(self):
        return super().available and isinstance(self._item("flow.autoAdaptation.enabled"), bool)

    @property
    def is_on(self):
        return self._item("flow.autoAdaptation.enabled") is True

    async def async_turn_on(self, **kwargs):
        await TadoXClient(self._main).set_flow(enabled=True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs):
        await TadoXClient(self._main).set_flow(enabled=False)
        await self.coordinator.async_request_refresh()


class TadoXAdaptedFlowSensor(TadoXSettingsEntity, SensorEntity):
    """Calculated automatic flow cap, not measured physical boiler flow."""

    _attr_name = "Optimised heating flow limit"
    _attr_icon = "mdi:thermometer-chevron-down"
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, settings, main):
        super().__init__(settings, main, "flow_optimized_limit")

    @property
    def available(self):
        return super().available and self._item("flow.autoAdaptation.maxFlowTemperature") is not None

    @property
    def native_value(self):
        return self._item("flow.autoAdaptation.maxFlowTemperature")

    @property
    def extra_state_attributes(self):
        return {"meaning": "tado-calculated maximum (not measured boiler flow)"}


class TadoXDhwModeSelect(TadoXSettingsEntity, SelectEntity):
    """Select tado X DHW Auto (resume), boost ON, or force OFF."""

    _attr_name = "DHW operating mode"
    _attr_icon = "mdi:water-boiler"
    _attr_options = ["Auto", "On", "Off"]

    def __init__(self, settings, main):
        super().__init__(settings, main, "dhw_operating_mode")

    @property
    def available(self):
        state = self._item("dhw.state")
        return super().available and isinstance(state, str) and state.upper() != "NONE"

    @property
    def current_option(self):
        value = self._item("dhw.state")
        if not isinstance(value, str):
            return None
        value = value.upper()
        if value.startswith("SCHEDULE"):
            return "Auto"
        if value.endswith("_ON") or value == "ON":
            return "On"
        if value.endswith("_OFF") or value == "OFF":
            return "Off"
        return None

    async def async_select_option(self, option):
        api = TadoXClient(self._main)
        if option == "Auto":
            await api.dhw_resume()
        elif option in ("On", "Off"):
            await api.dhw_boost(option.upper())
        else:
            raise ValueError("Unsupported DHW mode")
        await self.coordinator.async_request_refresh()


class TadoXRoomCapacityNumber(TadoZoneEntity, NumberEntity):
    """Locally configured rated radiator capacity used only for estimates.

    Default is 1 kW per VA family radiator thermostat in the room. This is an
    assumption, not hardware-reported radiator size or measured output.
    """

    _attr_name = "Estimated radiator capacity"
    _attr_icon = "mdi:radiator"
    _attr_native_unit_of_measurement = "kW"
    _attr_native_min_value = 0.1
    _attr_native_max_value = 15.0
    _attr_native_step = 0.1
    _attr_mode = NumberMode.BOX

    def __init__(self, main, zone):
        super().__init__(zone["name"], main.home_id, zone["id"], main)
        self._attr_unique_id = f"{main.home_id}_x_room_{zone['id']}_radiator_capacity"
        self._room_id = str(zone["id"])

    @property
    def native_value(self):
        return _capacities(self.coordinator)[self._room_id]

    async def async_set_native_value(self, value):
        if not 0.1 <= value <= 15.0:
            raise ValueError("Radiator capacity must be 0.1–15 kW")
        entry = self.coordinator.config_entry
        capacities = dict(entry.options.get("x_capacity_kw", {}))
        capacities[self._room_id] = float(value)
        self.hass.config_entries.async_update_entry(
            entry, options={**entry.options, "x_capacity_kw": capacities},
        )
        self.async_write_ha_state()


class TadoXSettingHistorySensor(TadoXSettingsEntity, SensorEntity):
    """Long-term Recorder sensor for an otherwise editable settings entity.

    Unlike the number/switch entities, measurement sensors retain hourly means
    after Home Assistant purges ordinary state history.
    """

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, settings, main, suffix, name, path):
        super().__init__(settings, main, suffix)
        self._attr_name = name
        self._path = path

    @property
    def available(self):
        return super().available and type(self._item(self._path)) in (int, float)

    @property
    def native_value(self):
        value = self._item(self._path)
        return value if type(value) in (int, float) else None


class TadoXAdaptationEnabledPercentSensor(TadoXSettingsEntity, SensorEntity):
    """A 0 or 100% numerical sensor, so monthly mean is % time enabled."""

    _attr_name = "Flow adaptation enabled percentage"
    _attr_icon = "mdi:autorenew"
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, settings, main):
        super().__init__(settings, main, "flow_adaptation_enabled_history")

    @property
    def available(self):
        return super().available and type(self._item("flow.autoAdaptation.enabled")) is bool

    @property
    def native_value(self):
        state = self._item("flow.autoAdaptation.enabled")
        return 100 if state is True else 0 if state is False else None
