"""Offline regression: distinguish tado X room schedule and manual controls."""

import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

source=(Path(__file__).resolve().parents[1]/
        "custom_components"/"tado"/"room_override.py")
spec=importlib.util.spec_from_file_location("room_override_test",source)
module=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=module
spec.loader.exec_module(module)


class FakeZone:
    def __init__(self, *, overlay=False, power="ON", available=True,
                 termination=None):
        self.overlay_active=overlay
        self.power=power
        self.available=available
        self.overlay_termination_type=termination


def coord(states):
    return SimpleNamespace(
        zones=[{"id":id,"name":f"room_{id}"} for id in states],
        data={"zone":states},
    )


class RoomOverrideTests(unittest.TestCase):
    def test_schedule_vs_manual_same_target_temperature(self):
        scheduled={"manualControlTermination":None,
                   "setting":{"power":"ON","temperature":{"value":20}}}
        manual={"manualControlTermination":{"type":"NEXT_TIME_BLOCK"},
                "setting":{"power":"ON","temperature":{"value":20}}}
        self.assertEqual(module._read_zone(scheduled),("smart_schedule",None))
        self.assertEqual(module._read_zone(manual),
                         ("manual_override","NEXT_TIME_BLOCK"))
        report=module.room_override_report(coord({10:scheduled,11:manual}))
        self.assertEqual(report["manual_override_rooms"],["room_11"])
        self.assertEqual(report["schedule_count"],1)
        self.assertEqual(report["manual_override_count"],1)
        self.assertEqual(module.observed_home_mode(report)["effective_mode"],
                         "manual_override")

    def test_scheduled_off_does_not_mean_whole_house_off(self):
        states={2:FakeZone(overlay=False,power="OFF"),
                4:FakeZone(overlay=False,power="ON")}
        report=module.room_override_report(coord(states))
        mode=module.observed_home_mode(report)
        self.assertEqual(mode["effective_mode"],"schedule")
        self.assertEqual(mode["effective_mode_label"],"Following Schedules")
        self.assertTrue(report["all_following_schedules"])

    def test_all_rooms_manual_off_reports_heating_off(self):
        states={2:FakeZone(overlay=True,power="OFF"),
                4:FakeZone(overlay=True,power="OFF")}
        report=module.room_override_report(coord(states))
        self.assertEqual(report["manual_off_count"],2)
        self.assertEqual(module.observed_home_mode(report)["effective_mode"],"off")
        self.assertEqual(module.observed_home_mode(report)["effective_mode_label"],
                         "Heating Off")

    def test_unknown_prevents_false_schedule_claim(self):
        states={2:FakeZone(),4:FakeZone(available=False)}
        report=module.room_override_report(coord(states))
        self.assertEqual(report["unknown_count"],1)
        self.assertFalse(report["all_following_schedules"])
        self.assertEqual(module.observed_home_mode(report)["effective_mode"],"unknown")

    def test_pending_boost_keeps_boost_label_and_live_override_state(self):
        report=module.room_override_report(coord({
            2:FakeZone(overlay=True,power="ON"),
            4:FakeZone(overlay=True,power="ON"),
        }))
        requested={"mode":"top_boost","mode_label":"Top Boost",
                   "pending":True,"kind":"resume_and_adapt"}
        observed=module.observed_home_mode(report,requested)
        self.assertEqual(observed["effective_mode"],"top_boost")
        self.assertEqual(observed["effective_mode_label"],"Top Boost")
        self.assertEqual(observed["observed_mode"],"manual_override")
        self.assertEqual(observed["observed_room_states"],2)

    def test_external_resume_overrides_stale_ha_mode(self):
        report=module.room_override_report(coord({
            2:FakeZone(overlay=False),
            4:FakeZone(overlay=False),
        }))
        saved={"mode":"off","mode_label":"Heating Off","pending":False}
        observed=module.observed_home_mode(report,saved)
        self.assertEqual(observed["effective_mode"],"schedule")
        self.assertEqual(observed["effective_mode_label"],"Following Schedules")
        self.assertFalse(observed["room_schedule_interrupted"])

    def test_two_valves_belong_to_one_room_status(self):
        report=module.room_override_report(coord({11:FakeZone(overlay=True)}))
        self.assertEqual(report["total_rooms"],1)
        self.assertEqual(report["manual_override_count"],1)

if __name__=="__main__":
    unittest.main()
