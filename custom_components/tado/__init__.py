"""Support for the (unofficial) Tado API."""

from datetime import timedelta
from pathlib import Path
import asyncio
import logging

import PyTado
import PyTado.exceptions
from PyTado.interface import Tado

from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryError,
    ConfigEntryNotReady,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_FALLBACK,
    CONF_REFRESH_TOKEN,
    CONF_X_HOME_ENERGY,
    CONF_X_LEGACY_ENERGY_PROBE,
    CONST_OVERLAY_MANUAL,
    CONST_OVERLAY_TADO_DEFAULT,
    CONST_OVERLAY_TADO_MODE,
    CONST_OVERLAY_TADO_OPTIONS,
    DOMAIN,
)
from .coordinator import TadoDataUpdateCoordinator, TadoMobileDeviceUpdateCoordinator
from .models import TadoData
from .services import setup_services
from .tadox_ext import TadoXSettingsCoordinator
from .heating_modes import HeatingModeManager
from .heat_allocation import allocate_recent
from .x_features import energy_enabled, restore_used_legacy_energy_option

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.CLIMATE,
    Platform.DEVICE_TRACKER,
    Platform.SENSOR,
    Platform.SELECT,
    Platform.SWITCH,
    Platform.WATER_HEATER,
    Platform.NUMBER,
]

MIN_TIME_BETWEEN_UPDATES = timedelta(minutes=4)
SCAN_INTERVAL = timedelta(minutes=5)
SCAN_MOBILE_DEVICE_INTERVAL = timedelta(seconds=30)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up Tado."""

    setup_services(hass)
    # Serve schedule/consumption cards directly from this integration's HACS
    # package. Dashboard resource registration remains an explicit UI step.
    folder = Path(__file__).parent / "www"
    await hass.http.async_register_static_paths([
        StaticPathConfig("/tado/x-schedule-card.js",
                         str(folder / "tado-x-schedule-card.js"),
                         cache_headers=False),
        StaticPathConfig("/tado/x-heating-energy-card.js",
                         str(folder / "tado-x-heating-energy-card.js"),
                         cache_headers=False),
        StaticPathConfig("/tado/x-settings-history-card.js",
                         str(folder / "tado-x-settings-history-card.js"),
                         cache_headers=False),
    ])
    return True


type TadoConfigEntry = ConfigEntry[TadoData]


async def async_setup_entry(hass: HomeAssistant, entry: TadoConfigEntry) -> bool:
    """Set up Tado from a config entry."""
    if CONF_REFRESH_TOKEN not in entry.data:
        raise ConfigEntryAuthFailed

    _async_import_options_from_data_if_missing(hass, entry)

    _LOGGER.debug("Setting up Tado connection")
    _LOGGER.debug("Creating Tado instance using stored authentication")

    def create_tado_instance() -> tuple[Tado, str]:
        """Create a Tado instance, this time with a previously obtained refresh token."""
        tado = Tado(saved_refresh_token=entry.data[CONF_REFRESH_TOKEN])
        return tado, tado.device_activation_status()

    try:
        tado, device_status = await hass.async_add_executor_job(create_tado_instance)
    except PyTado.exceptions.TadoWrongCredentialsException as err:
        raise ConfigEntryError(f"Invalid Tado credentials. Error: {err}") from err
    except PyTado.exceptions.TadoException as err:
        raise ConfigEntryNotReady(f"Error during Tado setup: {err}") from err
    if device_status != "COMPLETED":
        raise ConfigEntryAuthFailed(
            f"Device login flow status is {device_status}. Starting re-authentication."
        )

    # Creating Tado can rotate the refresh token. Save it before any
    # coordinator calls, which might fail and abort setup.
    refresh_token = await hass.async_add_executor_job(tado.get_refresh_token)
    if refresh_token and refresh_token != entry.data[CONF_REFRESH_TOKEN]:
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_REFRESH_TOKEN: refresh_token}
        )
        _LOGGER.debug("Saved rotated Tado refresh token after authentication")

    _LOGGER.debug("Tado connection established")

    coordinator = TadoDataUpdateCoordinator(hass, entry, tado)
    await coordinator.async_config_entry_first_refresh()
    entry.async_on_unload(coordinator.cancel_post_action_room_refresh)

    # Preserve the original household's existing Vaillant allocations on
    # upgrade, without activating hard-coded radiator extras for other homes.
    await restore_used_legacy_energy_option(hass, entry, coordinator)

    mobile_coordinator = TadoMobileDeviceUpdateCoordinator(hass, entry, tado, coordinator)
    await mobile_coordinator.async_config_entry_first_refresh()

    coordinator.x_settings = None
    if coordinator.is_x:
        coordinator.x_settings = TadoXSettingsCoordinator(hass, coordinator)
        try:
            await coordinator.x_settings.async_refresh()
        except Exception:
            # Optional HOPS settings should never take down working tado heating.
            _LOGGER.warning("Unable to load optional tado X DHW/flow settings", exc_info=True)
    entry.runtime_data = TadoData(coordinator, mobile_coordinator)
    if coordinator.is_x:
        # Only show X/household actions in HA Developer Tools if at least
        # one loaded X home opted into them. Each handler additionally checks
        # its own per-entry flag before executing.
        setup_services(hass, extras=True)
    coordinator.x_heating_modes = None
    if coordinator.is_x:
        # Read the saved UTC Top Boost recovery before installing entities.
        # This may schedule a previously authorised recovery after HA restarts.
        coordinator.x_heating_modes = HeatingModeManager(hass, coordinator)
        await coordinator.x_heating_modes.async_start()
        entry.async_on_unload(coordinator.x_heating_modes.async_stop)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    if coordinator.is_x and energy_enabled(entry):
        coordinator.x_allocation_lock = asyncio.Lock()

        @callback
        def run_hourly_allocation(now) -> None:
            if coordinator.x_allocation_lock.locked():
                return

            async def run():
                async with coordinator.x_allocation_lock:
                    try:
                        await allocate_recent(hass, coordinator, days=3)
                    except Exception:
                        _LOGGER.warning(
                            "tado X / Vaillant optional heating estimate failed",
                            exc_info=True,
                        )
            hass.async_create_task(run())

        # Recorder produces hourly statistics a few minutes after the hour.
        # No new tado or Vaillant cloud API requests are issued by this task.
        entry.async_on_unload(
            async_track_time_change(hass, run_hourly_allocation, minute=15, second=0)
        )

    return True


async def async_migrate_entry(hass: HomeAssistant, entry: TadoConfigEntry) -> bool:
    """Migrate old entry."""

    if entry.version < 2:
        # Do not log credentials or refresh tokens.
        data = dict(entry.data)
        data.pop(CONF_USERNAME, None)
        data.pop(CONF_PASSWORD, None)
        hass.config_entries.async_update_entry(entry=entry, data=data, version=2)
        _LOGGER.debug("Migration to Tado entry version 2 successful")

    if entry.version < 3:
        # All tado X features remain enabled for all users; only household
        # Vaillant/radiator energy estimation is opt-in. Preserve it when
        # pre-existing v2 room-estimate statistics prove previous use.
        opts = dict(entry.options)
        if CONF_X_HOME_ENERGY not in opts:
            opts[CONF_X_HOME_ENERGY] = False
            opts[CONF_X_LEGACY_ENERGY_PROBE] = True
        hass.config_entries.async_update_entry(
            entry=entry, options=opts, version=3
        )
        _LOGGER.info("Migrated tado options to opt-in feature flags")
    return True


@callback
def _async_import_options_from_data_if_missing(
    hass: HomeAssistant, entry: TadoConfigEntry
):
    options = dict(entry.options)
    if CONF_FALLBACK not in options:
        options[CONF_FALLBACK] = entry.data.get(
            CONF_FALLBACK, CONST_OVERLAY_TADO_DEFAULT
        )
        hass.config_entries.async_update_entry(entry, options=options)

    if options[CONF_FALLBACK] not in CONST_OVERLAY_TADO_OPTIONS:
        if options[CONF_FALLBACK]:
            options[CONF_FALLBACK] = CONST_OVERLAY_TADO_MODE
        else:
            options[CONF_FALLBACK] = CONST_OVERLAY_MANUAL
        hass.config_entries.async_update_entry(entry, options=options)


async def async_unload_entry(hass: HomeAssistant, entry: TadoConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
