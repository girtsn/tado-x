"""Unit tests for non-destructive, auto-managed Lovelace dashboard setup."""

import asyncio
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest


def stub(name, **attrs):
    value = ModuleType(name)
    for key, content in attrs.items():
        setattr(value, key, content)
    sys.modules[name] = value
    return value


stub("homeassistant", __path__=[])
stub("homeassistant.components", __path__=[])

registered = []
panels = set()


def panel_exists(hass, url):
    return url in panels


def register_panel(hass, component, **kw):
    panels.add(kw["frontend_url_path"])
    registered.append((component, kw))


frontend = stub("homeassistant.components.frontend",
                async_panel_exists=panel_exists,
                async_register_built_in_panel=register_panel)
import homeassistant.components
homeassistant.components.frontend = frontend


class NoConfig(Exception):
    pass


class FakeDashboardStorage:
    instances = []

    def __init__(self, hass, config):
        self.config = config
        self.saved = []
        self.persisted = getattr(hass, "saved_dashboard", None)
        self.__class__.instances.append(self)

    async def async_load(self, force):
        if self.persisted is None:
            raise NoConfig()
        return self.persisted

    async def async_save(self, config):
        self.persisted = config
        self.saved.append(config)


lovelace = stub("homeassistant.components.lovelace", __path__=[],
                LOVELACE_DATA="lovelace", MODE_STORAGE="storage",
                dashboard=SimpleNamespace(LovelaceStorage=FakeDashboardStorage))
homeassistant.components.lovelace = lovelace
stub("homeassistant.components.lovelace.const", ConfigNotFound=NoConfig)
root = "automanaged_dashboard_tests"
stub(root, __path__=[])
stub(root+".manifest_version", INTEGRATION_VERSION="2026.11.16")

path = (Path(__file__).resolve().parents[1]/
        "custom_components"/"tado"/"managed_dashboard.py")
spec=importlib.util.spec_from_file_location(root+".managed_dashboard",path)
module=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=module
spec.loader.exec_module(module)


class FakeResources:
    def __init__(self, existing=None):
        self.rows = list(existing or [])
        self.loaded = False
        self.created = []
        self.updated = []

    async def async_get_info(self):
        self.loaded = True
        return {"resources":len(self.rows)}

    def async_items(self):
        if not self.loaded:
            raise AssertionError("Resources read before loading")
        return self.rows

    async def async_update_item(self, id, payload):
        self.updated.append((id,payload))
        row=next(x for x in self.rows if x["id"]==id)
        row.update({"url":payload["url"],"type":payload["res_type"]})
        return row

    async def async_create_item(self, payload):
        row={"id":str(len(self.rows)+1),"type":payload["res_type"],
             "url":payload["url"]}
        self.created.append(row)
        self.rows.append(row)
        return row


class ManagedDashboardTests(unittest.TestCase):
    def setUp(self):
        registered.clear()
        panels.clear()
        FakeDashboardStorage.instances.clear()
        self.resources=FakeResources()
        self.data=SimpleNamespace(
            resource_mode="storage",resources=self.resources,dashboards={}
        )
        self.hass=SimpleNamespace(data={"lovelace":self.data})

    def test_autoregister_and_update_only_our_resource_urls(self):
        self.resources=FakeResources([
            {"id":"manual","type":"module","url":"/local/another-card.js?v=1"},
            {"id":"tado","type":"module",
             "url":"/tado/x-settings-history-card.js?v=2026.11.13"},
        ])
        self.data.resources=self.resources
        result=asyncio.run(module.async_install_managed_dashboard(self.hass))
        self.assertEqual(result["status"],"registered")
        self.assertTrue(self.resources.loaded)
        self.assertEqual(self.resources.rows[0]["url"],
                         "/local/another-card.js?v=1")
        self.assertIn("2026.11.16",self.resources.rows[1]["url"])
        self.assertEqual(len(self.resources.created),3)
        self.assertEqual(len(self.resources.updated),1)
        self.assertEqual(len(registered),1)
        self.assertEqual(
            FakeDashboardStorage.instances[0].saved,
            [{"strategy":{"type":"custom:tado-x-heating"}}],
        )

    def test_repeated_setup_does_not_duplicate_dashboard_or_resources(self):
        asyncio.run(module.async_install_managed_dashboard(self.hass))
        created=len(self.resources.rows)
        result=asyncio.run(module.async_install_managed_dashboard(self.hass))
        self.assertEqual(result["status"],"existing_preserved")
        self.assertEqual(len(self.resources.rows),created)
        self.assertEqual(len(registered),1)

    def test_manual_dashboard_collision_is_preserved(self):
        self.data.dashboards["tado-x-heating"]=object()
        result=asyncio.run(module.async_install_managed_dashboard(self.hass))
        self.assertEqual(result["status"],"existing_preserved")
        self.assertIsNotNone(self.data.dashboards["tado-x-heating"])
        self.assertEqual(len(registered),0)

    def test_existing_tado_managed_customization_is_not_overwritten(self):
        self.hass.saved_dashboard={"views":[{"title":"My custom layout"}]}
        result=asyncio.run(module.async_install_managed_dashboard(self.hass))
        self.assertEqual(result["status"],"registered")
        self.assertEqual(FakeDashboardStorage.instances[0].saved,[])

    def test_yaml_resource_mode_does_not_modify_user_files(self):
        self.data.resource_mode="yaml"
        result=asyncio.run(module.async_install_managed_dashboard(self.hass))
        self.assertEqual(result["status"],"yaml_resources_manual")
        self.assertEqual(len(registered),0)
        self.assertEqual(len(self.resources.rows),0)

    def test_no_lovelace_no_side_effect(self):
        self.hass.data={}
        result=asyncio.run(module.async_install_managed_dashboard(self.hass))
        self.assertEqual(result["status"],"lovelace_missing")
        self.assertEqual(len(registered),0)

    def test_duplicate_manual_resources_preserved(self):
        self.resources=FakeResources([
            {"id":"a","type":"module",
             "url":"/tado/x-schedule-card.js?v=1"},
            {"id":"b","type":"module",
             "url":"/tado/x-schedule-card.js?v=2"},
        ])
        self.data.resources=self.resources
        asyncio.run(module.async_install_managed_dashboard(self.hass))
        self.assertEqual(len(self.resources.updated),0)
        self.assertEqual(len(self.resources.rows),5) # 3 other modules added

if __name__=="__main__":
    unittest.main()
