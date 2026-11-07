"""Unit checks for the X home geofence response parser (no HA required)."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

_MODULE = Path(__file__).resolve().parents[1] / "custom_components/tado/presence_mode.py"
_spec = importlib.util.spec_from_file_location("tado_presence_mode", _MODULE)
_module = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(_module)


class TadoPresenceModeTests(unittest.TestCase):
    def test_auto_has_independent_effective_home(self):
        data = {"presenceLocked": False, "presence": "HOME"}
        self.assertEqual(_module.selected_presence_mode(data), "Auto")
        self.assertEqual(_module.effective_presence(data), "Home")

    def test_auto_has_independent_effective_away(self):
        data = {"presenceLocked": False, "presence": "AWAY"}
        self.assertEqual(_module.selected_presence_mode(data), "Auto")
        self.assertEqual(_module.effective_presence(data), "Away")

    def test_manually_locked_modes(self):
        for state in ("HOME", "AWAY"):
            data = {"presenceLocked": True, "presence": state}
            self.assertEqual(_module.selected_presence_mode(data), state.title())
            self.assertEqual(_module.effective_presence(data), state.title())

    def test_unknown_and_incomplete_responses_not_assumed_home(self):
        for data in (None, {}, {"presenceLocked": True},
                     {"presenceLocked": True, "presence": "INVALID"},
                     {"presenceLocked": "false", "presence": "HOME"}):
            self.assertIsNone(_module.selected_presence_mode(data))
        self.assertIsNone(_module.effective_presence({"presence": "INVALID"}))
        self.assertIsNone(_module.effective_presence(None))
        self.assertIsNone(_module.effective_presence({"presence": None}))

    def test_auto_selection_still_known_when_effective_state_missing(self):
        self.assertEqual(
            _module.selected_presence_mode({"presenceLocked": False}),
            "Auto",
        )
        self.assertIsNone(_module.effective_presence({"presenceLocked": False}))


if __name__ == "__main__":
    unittest.main()
