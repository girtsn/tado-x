"""Static regression: managed panel and one conditional dashboard example.

Live panel registration requires a real Home Assistant frontend, so this
offline test checks the public contract without fabricating a HA server.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
TADO = ROOT / "custom_components" / "tado"
EXAMPLE = ROOT / "examples" / "heating_dashboard.yaml"


class ManagedHeatingPanelTests(unittest.TestCase):
    def test_bundle_has_automatic_panel_and_no_lovelace_resource_dependency(self):
        backend = (TADO / "__init__.py").read_text()
        panel = (TADO / "www" / "tado-x-managed-panel.js").read_text()
        self.assertIn('frontend_url_path="tado-x-heating"', backend)
        self.assertIn('webcomponent_name="tado-x-managed-heating-panel"', backend)
        self.assertIn('module_url=f"/tado/x-managed-panel.js?v={INTEGRATION_VERSION}"', backend)
        for component in (
            "tado-x-settings-history-card",
            "tado-x-schedule-card",
            "tado-x-heating-energy-card",
        ):
            self.assertIn('import("./x-', panel)
            self.assertIn(f'"{component}"', panel)
        self.assertIn("_energyEnabled()", panel)
        self.assertIn("household_vaillant_mypyllant_gas_allocation", panel)
        self.assertIn("this._tab===\"overview\"", panel)
        self.assertIn("date-range-changed", panel)
        self.assertIn('"last3years"', panel)
        self.assertIn("shared_date_range:this._tab", panel)
        self.assertIn('new URL(import.meta.url)', panel)
        self.assertIn('encodeURIComponent(XH_ASSET_VERSION)', panel)
        self.assertIn('sidebar_icon="mdi:gas-burner"', backend)
        self.assertIn('"integration_version": INTEGRATION_VERSION', backend)
        self.assertIn("oldVersion!==value.config.integration_version", panel)
        self.assertIn('cache_headers=False', backend)


    def test_exact_range_supported_on_both_history_cards(self):
        backend = (TADO / "heat_allocation.py").read_text()
        service = (TADO / "services.py").read_text()
        settings = (TADO / "www" / "tado-x-settings-history-card.js").read_text()
        gas = (TADO / "www" / "tado-x-heating-energy-card.js").read_text()
        self.assertIn("start_time: str | None", backend)
        self.assertIn("end_time: str | None", backend)
        self.assertIn("end - start > timedelta(days=1099)", backend)
        self.assertIn("start_time=call.data.get", service)
        self.assertIn("end_time=call.data.get", service)
        self.assertIn('this._dateRange.start', settings)
        self.assertIn('this._dateRange.end', settings)
        self.assertIn('args.start_time=this._dateRange.start', gas)
        self.assertIn('args.end_time=this._dateRange.end', gas)

    def test_only_one_vaillant_option_not_advanced_tado_switches(self):
        flow = (TADO / "config_flow.py").read_text()
        self.assertIn("CONF_X_HOME_ENERGY", flow)
        self.assertNotIn("CONF_X_ADVANCED", flow)
        binary = (TADO / "binary_sensor.py").read_text()
        self.assertIn("TadoXVaillantEnergyEnabledBinarySensor", binary)
        self.assertIn("read_only", binary)

    def test_generic_yaml_hides_entire_vaillant_section(self):
        yaml = EXAMPLE.read_text()
        self.assertIn("visibility:", yaml)
        self.assertIn("binary_sensor.tado_x_vaillant_energy_enabled", yaml)
        self.assertIn('state: "on"', yaml)
        self.assertIn("custom:tado-x-heating-energy-card", yaml)
        self.assertEqual(yaml.count("title: Schedules"), 1)
        self.assertNotIn("25.748", yaml)
        self.assertNotIn("6538", yaml)

    def test_no_yaml_automations_or_helpers_needed_for_boost_recovery(self):
        modes = (TADO / "heating_modes.py").read_text()
        self.assertIn("async_recover", modes)
        self.assertIn("async_start", modes)
        self.assertIn("async_save", modes)


if __name__ == "__main__":
    unittest.main()
