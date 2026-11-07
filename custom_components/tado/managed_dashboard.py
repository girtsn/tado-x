"""Automatic, integration-managed tado X Heating dashboard.

The dashboard is a Lovelace *strategy*, not a copied YAML file. Its layout
comes from the versioned JavaScript installed with the integration. Updates
do not overwrite a customized user dashboard, its content, or existing helpers.

Only storage-mode Lovelace resource registration is automatic; in YAML
resource mode Home Assistant deliberately leaves the resource list under
the user's configuration.yaml ownership. In that case we never attempt an
unsafe resource write or create a dashboard that would fail to render.
"""

from __future__ import annotations

import logging
from urllib.parse import urlsplit

from homeassistant.components import frontend
from homeassistant.components.lovelace import LOVELACE_DATA, MODE_STORAGE, dashboard
from homeassistant.components.lovelace.const import CONF_URL_PATH

from .manifest_version import INTEGRATION_VERSION

_LOGGER = logging.getLogger(__name__)

MANAGED_DASHBOARD_PATH = "tado-x-heating"
STRATEGY = {"strategy": {"type": "custom:tado-x-heating"}}
RESOURCE_FILES = (
    "tado-x-settings-history-card.js",
    "tado-x-schedule-card.js",
    "tado-x-heating-energy-card.js",
    "tado-x-heating-dashboard.js",
)


def desired_resources(version: str = INTEGRATION_VERSION) -> tuple[str, ...]:
    """Same URLs are auto-versioned on each integration update."""
    return tuple(f"/tado/{filename}?v={version}" for filename in RESOURCE_FILES)


async def _sync_resources(hass, lovelace_data) -> bool:
    """Safely create/update JS module resources without touching other cards.

    HA storage resource mode supports the collection APIs. For YAML-managed
    resources, integration writers must not modify user configuration.
    """
    if lovelace_data.resource_mode != MODE_STORAGE:
        _LOGGER.warning(
            "tado X managed dashboard: Lovelace resources are configured "
            "in YAML; add /tado/x-heating-dashboard.js as a module manually "
            "or switch resource_mode to storage. No dashboard was modified."
        )
        return False

    resources = lovelace_data.resources
    # Important: explicitly load the resource collection before listing,
    # so we do not clobber other registered Lovelace resources on startup.
    await resources.async_get_info()
    existing = list(resources.async_items())

    for desired in desired_resources():
        path = urlsplit(desired).path
        matches = [
            resource for resource in existing
            if urlsplit(str(resource.get("url", ""))).path == path
        ]
        if len(matches) > 1:
            _LOGGER.warning(
                "Found multiple Lovelace resource registrations for %s; "
                "keep user registrations intact and remove duplicates "
                "manually before auto-updates",
                path,
            )
            continue
        if matches:
            resource = matches[0]
            if resource.get("url") != desired or resource.get("type") != "module":
                await resources.async_update_item(
                    resource["id"], {"url": desired, "res_type": "module"}
                )
                resource["url"] = desired
                resource["type"] = "module"
        else:
            created = await resources.async_create_item({
                "url": desired, "res_type": "module"
            })
            existing.append(created)
    return True


async def _ensure_managed_dashboard(hass, lovelace_data) -> str:
    """Create a separate strategy dashboard once; never edit a user's cards.

    Home Assistant's Lovelace storage has dashboard metadata in one
    collection, but the runtime dashboard mapping is not itself exposed as
    the collection. When creating a new dashboard after HA startup, create
    the metadata, register the Lovelace panel and save the initial strategy.
    Subsequent startups load this storage dashboard through HA normally.
    """
    url = MANAGED_DASHBOARD_PATH
    if url in lovelace_data.dashboards or frontend.async_panel_exists(hass, url):
        # Existing dashboard at the same path is wholly user-owned. If it
        # uses our strategy, its layout still updates with the JS resource.
        return "existing_preserved"

    collection = dashboard.DashboardsCollection(hass)
    await collection.async_load()
    # Avoid overwriting collisions in stored metadata even if a panel is not
    # currently visible/registered.
    for item in collection.async_items():
        if item.get(CONF_URL_PATH) == url:
            return "existing_preserved"

    item = await collection.async_create_item({
        "url_path": url,
        "title": "tado X Heating",
        "icon": "mdi:radiator",
        "show_in_sidebar": True,
        "require_admin": False,
    })
    managed = dashboard.LovelaceStorage(hass, item)
    lovelace_data.dashboards[url] = managed
    try:
        frontend.async_register_built_in_panel(
            hass, "lovelace", frontend_url_path=url,
            sidebar_title="tado X Heating", sidebar_icon="mdi:radiator",
            show_in_sidebar=True, require_admin=False,
            config={"mode": MODE_STORAGE},
        )
        await managed.async_save(STRATEGY)
    except Exception:
        # The storage collection retains a metadata entry; next startup
        # Lovelace will load it normally. Never affect other dashboards.
        _LOGGER.exception("Could not initialize managed tado X dashboard")
        return "creation_incomplete"
    return "created"


async def async_install_managed_dashboard(hass) -> dict[str, str]:
    """Install the resource and managed dashboard after Lovelace is ready.

    Called by tado's setup after HA startup, never from a synchronous hook.
    """
    data = hass.data.get(LOVELACE_DATA)
    if data is None:
        _LOGGER.debug("Lovelace is not installed; skip tado X managed dashboard")
        return {"status": "lovelace_missing"}
    if not await _sync_resources(hass, data):
        return {"status": "yaml_resources_manual"}
    result = await _ensure_managed_dashboard(hass, data)
    _LOGGER.info(
        "tado X managed dashboard: %s at /%s",
        result, MANAGED_DASHBOARD_PATH,
    )
    return {"status": result, "path": MANAGED_DASHBOARD_PATH}
