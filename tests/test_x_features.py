"""Offline regression for optional household energy feature.

Use isolated fake package modules: this does not import Home Assistant,
PyTado or touch a live heating system.
"""
import asyncio
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest

PACKAGE = "optional_features_test"
pkg = ModuleType(PACKAGE)
pkg.__path__ = []
sys.modules[PACKAGE] = pkg

constants = ModuleType(PACKAGE + ".const")
constants.CONF_X_HOME_ENERGY = "x_household_energy"
constants.CONF_X_LEGACY_ENERGY_PROBE = "x_legacy_energy_probe"
sys.modules[constants.__name__] = constants

heat = ModuleType(PACKAGE + ".heat_allocation")
heat._stat_id = lambda coord, zid: (
    f"tado:x_radiator_weighted_gas_heating_v2_{coord.home_id}_{zid}"
)
sys.modules[heat.__name__] = heat

path = (Path(__file__).resolve().parents[1]
        / "custom_components" / "tado" / "x_features.py")
spec = importlib.util.spec_from_file_location(PACKAGE + ".x_features", path)
features = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = features
spec.loader.exec_module(features)


class FakeConfigEntries:
    def async_update_entry(self, entry, *, options):
        entry.options = dict(options)


class OptInTests(unittest.TestCase):
    def setUp(self):
        self.hass = SimpleNamespace(config_entries=FakeConfigEntries())
        self.coord = SimpleNamespace(
            is_x=True, home_id=321, zones=[{"id": 2}, {"id": 11}]
        )
        self.stat = heat._stat_id(self.coord, 2)

    def test_new_integrations_default_to_tado_features_without_vaillant(self):
        entry = SimpleNamespace(options={})
        self.assertFalse(features.energy_enabled(entry))
        self.assertFalse(asyncio.run(features.restore_used_legacy_energy_option(
            self.hass, entry, self.coord
        )))
        self.assertEqual(entry.options, {})

    def test_legacy_household_already_used_room_stats_remains_enabled(self):
        entry = SimpleNamespace(options={
            "fallback": "TADO_DEFAULT",
            "x_capacity_kw": {"2": 3.993},
            "x_household_energy": False,
            "x_legacy_energy_probe": True,
        })

        async def fetch(_hass, _start, _end, ids, *, period):
            self.assertEqual(period, "day")
            self.assertIn(self.stat, ids)
            return {self.stat: [{"start": 1, "sum": 12.4}]}
        heat._fetch = fetch
        enabled = asyncio.run(features.restore_used_legacy_energy_option(
            self.hass, entry, self.coord
        ))
        self.assertTrue(enabled)
        self.assertTrue(features.energy_enabled(entry))
        self.assertFalse(entry.options["x_legacy_energy_probe"])
        self.assertEqual(entry.options["x_capacity_kw"]["2"], 3.993)

    def test_unrelated_existing_home_not_auto_enabled(self):
        entry = SimpleNamespace(options={
            "x_legacy_energy_probe": True,
            "x_household_energy": False,
        })

        async def fetch(*args, **kwargs):
            return {self.stat: []}
        heat._fetch = fetch
        enabled = asyncio.run(features.restore_used_legacy_energy_option(
            self.hass, entry, self.coord
        ))
        self.assertFalse(enabled)
        self.assertFalse(features.energy_enabled(entry))
        self.assertFalse(entry.options["x_legacy_energy_probe"])

    def test_recorder_error_keeps_probe_pending_but_feature_off(self):
        entry = SimpleNamespace(options={
            "x_household_energy": False,
            "x_legacy_energy_probe": True,
        })

        async def fetch(*args, **kwargs):
            raise RuntimeError("recorder still starting")
        heat._fetch = fetch
        enabled = asyncio.run(features.restore_used_legacy_energy_option(
            self.hass, entry, self.coord
        ))
        self.assertFalse(enabled)
        self.assertTrue(entry.options["x_legacy_energy_probe"])
        self.assertFalse(features.energy_enabled(entry))

    def test_only_vaillant_is_a_feature_toggle(self):
        a = SimpleNamespace(options={"x_household_energy": False})
        b = SimpleNamespace(options={"x_household_energy": True})
        self.assertFalse(features.energy_enabled(a))
        self.assertTrue(features.energy_enabled(b))


if __name__ == "__main__":
    unittest.main()
