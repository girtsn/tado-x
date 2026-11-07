"""Offline check: R01–R11 are PHYSICAL radiators, not tado R1–R10."""

import importlib.util
from pathlib import Path
import sys
from types import ModuleType
import unittest

# Install minimal Home Assistant imports for unit tests without a running HA.
ha=sys.modules.setdefault("homeassistant",ModuleType("homeassistant"))
errors=sys.modules.setdefault("homeassistant.exceptions", ModuleType("homeassistant.exceptions"))
if not hasattr(errors,"HomeAssistantError"):
    errors.HomeAssistantError=type("HomeAssistantError",(Exception,),{})

SOURCE=Path(__file__).resolve().parents[1]/"custom_components"/"tado"/"radiator_inventory.py"
spec=importlib.util.spec_from_file_location("radiator_inventory_test", SOURCE)
inventory=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=inventory
spec.loader.exec_module(inventory)


def room(room_id, name, valve_count=1, remote=False):
    return {
        "id":room_id, "name":name,
        "devices":[
            *[{"type":"VA04"} for _ in range(valve_count)],
            *([{"type":"RU04"}] if remote else []),
        ],
    }


def all_rooms():
    return [
        room(551, "0fl Living room"),
        room(664, "0fl Entrance hallway"),
        room(332, "0fl Kitchen"),
        room(987, "0fl Toilet"),
        room(5519, "1fl Yard-side bedroom"),
        room(521, "1fl Street-side bedroom"),
        room(904, "1fl Small bedroom (yard-side)"),
        room(107, "1fl Bathroom", remote=True),
        room(86, "2fl Attic bedroom", valve_count=2),
        room(93, "2fl Attic bathroom"),
    ]


class RadiatorInventoryTests(unittest.TestCase):
    def test_eleven_physical_radiators_ten_rooms(self):
        self.assertEqual(len(inventory.RADIATORS),11)
        self.assertEqual(len(inventory.GROUP_PHYSICAL_IDS),10)
        self.assertEqual(sum(r.rated_output_w for r in inventory.RADIATORS),25748)
        self.assertEqual(set(inventory.GROUP_PHYSICAL_IDS["attic_bedroom"]),{"R09","R10"})
        self.assertEqual(inventory.GROUP_PHYSICAL_IDS["attic_bathroom"],("R11",))
        self.assertEqual(sum(inventory.BY_PHYSICAL_ID[r].rated_output_w
                             for r in inventory.GROUP_PHYSICAL_IDS["attic_bedroom"]),6538)

    def test_tado_room_ids_not_confused_with_physical_ids(self):
        report=inventory.radiator_capacity_report(all_rooms())
        self.assertEqual(report["matched_rooms"],10)
        self.assertEqual(report["total_inventory_w"],25748)
        self.assertEqual(report["matched_rated_w"],25748)
        capacities={r["room"]:r for r in report["rooms"]}
        self.assertEqual(capacities["0fl Entrance hallway"]["capacity_kw"],1.643)
        self.assertEqual(capacities["2fl Attic bedroom"]["capacity_kw"],6.538)
        self.assertEqual(capacities["2fl Attic bathroom"]["capacity_kw"],3.269)
        self.assertEqual(capacities["2fl Attic bedroom"]["radiator_ids"],["R09","R10"])
        self.assertEqual(capacities["2fl Attic bedroom"]["tado_radiator_valves"],2)
        self.assertEqual(capacities["1fl Bathroom"]["tado_radiator_valves"],1)
        self.assertNotEqual(capacities["0fl Entrance hallway"]["room_id"],2)

    def test_ambiguous_name_never_assigned(self):
        zones=[room(1,"Bedroom"),room(2,"Bathroom")]
        report=inventory.radiator_capacity_report(zones)
        self.assertEqual(report["matched_rooms"],0)
        self.assertEqual([r["capacity_kw"] for r in report["rooms"]],[None,None])
        with self.assertRaisesRegex(Exception,"needs review"):
            inventory.require_valid_capacities(zones)

    def test_manual_group_assignment_binds_tado_id_not_r_number(self):
        zones=[room(42,"My attic",2),room(99,"Bathroom")]
        report=inventory.radiator_capacity_report(
            zones,{},{"42":"attic_bedroom","99":"attic_bathroom"})
        self.assertEqual([r["capacity_kw"] for r in report["rooms"]],[6.538,3.269])
        self.assertEqual(report["rooms"][0]["room_mapping"],"manual_room_assignment")

    def test_existing_manual_capacity_takes_precedence(self):
        report=inventory.radiator_capacity_report(
            all_rooms(),{"551":4.5})
        self.assertEqual(report["rooms"][0]["capacity_kw"],4.5)
        self.assertEqual(report["rooms"][0]["source"],"manual_override")
        self.assertEqual(report["rooms"][0]["rated_w"],3993)

    def test_multiple_rooms_claiming_one_physical_group_are_rejected(self):
        zones=[room(1,"0fl Kitchen"),room(2,"0fl Kitchen")]
        report=inventory.radiator_capacity_report(zones)
        self.assertEqual([r["status"] for r in report["rooms"]],
                         ["ambiguous_multiple_tado_zones"]*2)
        self.assertEqual([r["capacity_kw"] for r in report["rooms"]],[None,None])

    def test_two_valves_does_not_map_to_the_wrong_physical_r02(self):
        zones=[room(2,"unknown room",2),room(3,"Entrance hallway")]
        report=inventory.radiator_capacity_report(zones)
        self.assertEqual(report["rooms"][0]["status"],"unmatched_needs_room_mapping")
        self.assertEqual(report["rooms"][1]["radiator_ids"],["R02"])
        self.assertEqual(report["rooms"][1]["capacity_kw"],1.643)


if __name__=="__main__":
    unittest.main()
