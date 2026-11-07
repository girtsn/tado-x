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
from homeassistant.components.lovelace.const import ConfigNotFound

from .manifest_version import INTEGRATION_VERSION

_LOGGER = logging.getLogger(__name__)

MANAGED_DASHBOARD_PATH = "tado-x-heating"
STRATEGY = {"strategy": {"type": "custom:tado-x-heating"}}
RESOURCE_FILES = (
    "x-settings-history-card.js",
    "x-schedule-card.js",
    "x-heating-energy-card.js",
    "x-heating-dashboard.js",
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
    """Register an integration-owned Lovelace sidebar panel.

    Important: do NOT create another DashboardsCollection instance to edit
    Home Assistant's .storage/lovelace_dashboards. The live core collection
    retains its own in-memory snapshot, and a second instance could cause
    later user dashboard edits to overwrite the newly created metadata.

    Instead install a dedicated Lovelace panel and attach an independent
    strategy-backed LovelaceStorage at a stable path. The user's ordinary
    dashboard collection is never written. An existing panel/path (including
    the user's hand-managed /heating) is always preserved.
    """
    url = MANAGED_DASHBOARD_PATH
    if url in lovelace_data.dashboards or frontend.async_panel_exists(hass, url):
        return "existing_preserved"

    # The storage key is private to this tado-managed panel. The strategy
    # config is seeded only on first use; a user's "Take control" edit is
    # never overwritten by a future integration update.
    config = {
        "id": "tado-x-heating-managed",
        "url_path": url,
        "title": "tado X Heating",
        "icon": "mdi:radiator",
        "show_in_sidebar": True,
        "require_admin": False,
    }
    managed = dashboard.LovelaceStorage(hass, config)
    try:
        try:
            await managed.async_load(False)
        except ConfigNotFound:
            await managed.async_save(STRATEGY)

        lovelace_data.dashboards[url] = managed
        frontend.async_register_built_in_panel(
            hass, "lovelace", frontend_url_path=url,
            sidebar_title="tado X Heating", sidebar_icon="mdi:radiator",
            show_in_sidebar=True, require_admin=False,
            config={"mode": MODE_STORAGE},
        )
    except Exception:
        lovelace_data.dashboards.pop(url, None)
        _LOGGER.exception("Could not register integration-owned tado X dashboard")
        return "creation_incomplete"
    return "registered"

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
