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
        picker = (TADO / "www" / "tado-x-date-range-picker.js").read_text()
        self.assertIn('"last3years"', picker)
        self.assertIn('x-date-range-picker.js?v=', panel)
        self.assertIn("shared_date_range:this._tab", panel)
        self.assertIn('new URL(import.meta.url)', panel)
        self.assertIn('encodeURIComponent(XH_ASSET_VERSION)', panel)
        self.assertIn('sidebar_icon="mdi:gas-burner"', backend)
        self.assertIn('"integration_version": INTEGRATION_VERSION', backend)
        self.assertIn("oldVersion!==value.config.integration_version", panel)
        self.assertIn('cache_headers=False', backend)


    def test_sidebar_module_loading_is_nonblocking_and_recoverable(self):
        panel = (TADO / "www" / "tado-x-managed-panel.js").read_text()
        self.assertNotIn('const {xhPresetRange}=await import(', panel)
        self.assertIn('let xhPresetRange=null', panel)
        self.assertIn('this._ensureAssets();', panel)
        self.assertIn('this._assetsReady', panel)
        self.assertIn('Retry loading', panel)
        self.assertIn('this._renderAssetStatus();', panel)
        self.assertIn('tado-x-panel-reload-', panel)
        self.assertIn('window.sessionStorage.getItem(key)', panel)
        self.assertIn('new URL(import.meta.url)', panel)

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
        self.assertIn('start_time:this._dateRange.start', gas)
        self.assertIn('end_time:this._dateRange.end', gas)
        for source in (settings, gas):
            self.assertIn('tado-x-date-range-picker', source)
            self.assertIn('date-range-changed', source)
            self.assertNotIn('this._period', source)
            self.assertNotIn('XH_PERIODS', source)
        self.assertIn('/tado/x-date-range-picker.js', (TADO / '__init__.py').read_text())

    def test_independent_tado_x_cloud_health_and_dashboard_status(self):
        binary = (TADO / "binary_sensor.py").read_text()
        sensor = (TADO / "sensor.py").read_text()
        main = (TADO / "coordinator.py").read_text()
        extra = (TADO / "tadox_ext.py").read_text()
        panel = (TADO / "www" / "tado-x-managed-panel.js").read_text()
        history = (TADO / "www" / "tado-x-settings-history-card.js").read_text()
        strip = (TADO / "www" / "tado-x-connectivity-status.js").read_text()

        for scope in ("main_api", "settings_api"):
            self.assertIn(f'"{scope}"', binary)
        self.assertIn('class TadoXCloudConnectionBinarySensor', binary)
        self.assertIn('def available(self) -> bool:', binary)
        self.assertIn('return True', binary)
        self.assertIn('source.last_update_success', binary)
        self.assertIn('async_track_time_interval', binary)
        self.assertIn('self._source.async_add_listener', binary)
        self.assertIn('stale_timeout_minutes', binary)
        self.assertIn('last_successful_update = datetime.now(timezone.utc)', main)
        self.assertIn('last_successful_update = datetime.now(timezone.utc)', extra)
        self.assertIn('class TadoXLastSuccessfulUpdateSensor', sensor)
        self.assertIn('SensorDeviceClass.TIMESTAMP', sensor)
        self.assertIn('tado-x-connectivity-status', panel)
        self.assertIn('tado-x-connectivity-status', history)
        self.assertIn('connectivity_scope', strip)
        self.assertIn('date-range-changed', panel)
        # No household notification automation is distributed via HACS.
        self.assertFalse(
            (ROOT / "examples" / "device_availability_dynamic_email.yaml").exists()
        )

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
