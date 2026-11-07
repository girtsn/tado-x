"""Offline tests of estimated gas-input allocation; no Home Assistant/boiler calls."""

import asyncio
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch


def fake_module(name, **members):
    existing=sys.modules.get(name)
    if existing:
        existing.__dict__.update(members)
        return existing
    mod=ModuleType(name);mod.__dict__.update(members);sys.modules[name]=mod
    return mod


class FakeStat(dict):
    """Match native Home Assistant StatisticData, a TypedDict."""



fake_module("homeassistant")
fake_module("homeassistant.components")
fake_module("homeassistant.components.recorder", get_instance=lambda hass:None)
fake_module("homeassistant.components.recorder.statistics",
            StatisticData=FakeStat,
            StatisticMetaData=dict,
            StatisticMeanType=SimpleNamespace(NONE="none"),
            async_add_external_statistics=lambda hass,meta,rows:None,
            statistics_during_period=lambda *args:None)
fake_module("homeassistant.helpers")
fake_module("homeassistant.helpers.entity_registry", async_get=lambda hass:None)
fake_module("homeassistant.exceptions",
            HomeAssistantError=type("HomeAssistantError",(Exception,),{}))

SOURCE=Path(__file__).resolve().parents[1]/"custom_components"/"tado"/"heat_allocation.py"
# Load the new radiator inventory module via its package name, without
# importing the actual Home Assistant installation into offline unit tests.
fake_module("custom_components", __path__=[])
fake_module("custom_components.tado", __path__=[])
inv_name="custom_components.tado.radiator_inventory"
inv_spec=importlib.util.spec_from_file_location(inv_name,SOURCE.with_name("radiator_inventory.py"))
inventory=importlib.util.module_from_spec(inv_spec)
sys.modules[inv_name]=inventory
inv_spec.loader.exec_module(inventory)
spec=importlib.util.spec_from_file_location("custom_components.tado.heat_allocation",SOURCE)
allocation=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=allocation
spec.loader.exec_module(allocation)


class AllocationTests(unittest.TestCase):
    def setUp(self):
        self.main=SimpleNamespace(
            home_id=123, is_x=True,
            zones=[{"id":101,"name":"Kitchen"},{"id":102,"name":"Bath"}],
            config_entry=SimpleNamespace(options={}),
        )
        self.hass=SimpleNamespace(data={})
        self.end=datetime.now(timezone.utc).replace(minute=0,second=0,microsecond=0)
        self.t0=(self.end-timedelta(hours=2)).timestamp()
        self.t1=(self.end-timedelta(hours=1)).timestamp()
        self.writes=[]

    def snapshots(self, room1_mean=25, room2_mean=75):
        return {
            "mypyllant:heating": [
                {"start":self.t0,"sum":1000},
                {"start":self.t1,"sum":3000},
            ],
            "sensor.r1": [{"start":self.t1,"mean":room1_mean}],
            "sensor.r2": [{"start":self.t1,"mean":room2_mean}],
        }

    async def run_case(self, raw, dry_run=False):
        async def fetch(*args,**kwargs):
            return raw
        with (patch.object(allocation,"_gas_statistic",return_value="mypyllant:heating"),
              patch.object(allocation,"_room_sensor_ids",
                           return_value={"101":"sensor.r1","102":"sensor.r2"}),
              patch.object(allocation,"_capacities",
                           return_value={"101":1.0,"102":1.0}),
              patch.object(allocation,"_fetch",fetch),
              patch.object(allocation,"async_add_external_statistics",
                           lambda hass,meta,rows:self.writes.append((meta,rows)))):
            return await allocation.allocate_recent(
                self.hass,self.main,days=1,dry_run=dry_run)

    def test_one_hour_allocates_proportionally(self):
        result=asyncio.run(self.run_case(self.snapshots()))
        self.assertEqual(result["hours"],1)
        self.assertEqual(result["gas_heating_kwh"],2)
        self.assertEqual(result["allocated_kwh"],2)
        self.assertEqual(result["unallocated_kwh"],0)
        by_name={meta["statistic_id"]:rows[0]["state"]
                 for meta,rows in self.writes}
        self.assertAlmostEqual(by_name[allocation._stat_id(self.main,"101")],.5)
        self.assertAlmostEqual(by_name[allocation._stat_id(self.main,"102")],1.5)

    def test_missing_room_history_is_unallocated(self):
        result=asyncio.run(self.run_case(self.snapshots(room2_mean=None)))
        self.assertEqual(result["allocated_kwh"],0)
        self.assertEqual(result["unallocated_kwh"],2)
        by_name={meta["statistic_id"]:rows[0]["state"]
                 for meta,rows in self.writes}
        self.assertAlmostEqual(by_name[allocation._stat_id(self.main,"unallocated")],2)

    def test_two_hours_preserve_cumulative_sums(self):
        tminus3=(self.end-timedelta(hours=3)).timestamp()
        raw={
            "mypyllant:heating": [
                {"start":tminus3,"sum":1000},
                {"start":self.t0,"sum":3000},
                {"start":self.t1,"sum":5000},
            ],
            "sensor.r1":[
                {"start":self.t0,"mean":25},
                {"start":self.t1,"mean":50},
            ],
            "sensor.r2":[
                {"start":self.t0,"mean":75},
                {"start":self.t1,"mean":50},
            ],
        }
        result=asyncio.run(self.run_case(raw))
        self.assertEqual(result["hours"],2)
        self.assertEqual(result["gas_heating_kwh"],4)
        by_name={meta["statistic_id"]:rows for meta,rows in self.writes}
        room1=by_name[allocation._stat_id(self.main,"101")]
        room2=by_name[allocation._stat_id(self.main,"102")]
        self.assertEqual(len(room1),2)
        self.assertAlmostEqual(room1[0]["sum"],.5)
        self.assertAlmostEqual(room1[1]["sum"],1.5)
        self.assertAlmostEqual(room2[1]["sum"],2.5)
        self.assertEqual(result["unallocated_kwh"],0)

    def test_diagnostic_separates_missing_from_all_zero_demand(self):
        """Hourly cause must match production allocation's decision tree."""
        tminus3 = (self.end-timedelta(hours=3)).timestamp()
        raw = {
            "mypyllant:heating": [
                {"start": tminus3, "sum": 1000},
                {"start": self.t0, "sum": 3000},
                {"start": self.t1, "sum": 5000},
            ],
            "sensor.r1": [
                {"start": self.t0, "mean": 25},
                {"start": self.t1, "mean": 0},
            ],
            "sensor.r2": [
                # Missing entire first hour: other room is actively heating.
                {"start": self.t1, "mean": 0},
            ],
        }
        async def fetch(*args, **kwargs):
            return raw
        with (
            patch.object(allocation, "_gas_statistic", return_value="mypyllant:heating"),
            patch.object(allocation, "_room_sensor_ids",
                         return_value={"101": "sensor.r1", "102": "sensor.r2"}),
            patch.object(allocation, "_fetch", fetch),
        ):
            result = asyncio.run(allocation.diagnose_unallocated(
                self.hass, self.main, days=1, limit=30
            ))
        self.assertEqual(result["status"], "diagnostic_completed")
        self.assertTrue(result["read_only"])
        self.assertEqual(result["valid_gas_hours"], 2)
        self.assertEqual(result["gas_kwh_in_valid_hours"], 4)
        self.assertEqual(result["unallocated_kwh"], 4)
        self.assertEqual(result["unallocated_percent"], 100)
        causes = result["causes"]
        missing = causes["missing_or_invalid_room_demand"]
        zero = causes["all_rooms_zero_demand"]
        self.assertEqual((missing["hours"], missing["gas_kwh"]), (1, 2))
        self.assertEqual((zero["hours"], zero["gas_kwh"]), (1, 2))
        self.assertEqual(missing["hours_with_other_rooms_active"], 1)
        self.assertEqual(zero["hours_with_adjacent_demand"], 1)
        self.assertEqual(result["missing_room_breakdown"][0]["room"], "Bath")
        self.assertEqual(result["missing_room_breakdown"][0]["hours"], 1)
        self.assertEqual(len(result["highest_unallocated_hours"]), 2)
        self.assertEqual(len(result["days_with_unallocated"]), 1)

    def test_diagnostic_does_not_count_gas_when_room_is_actively_heating(self):
        raw = self.snapshots(room1_mean=25, room2_mean=75)
        async def fetch(*args, **kwargs):
            return raw
        with (
            patch.object(allocation, "_gas_statistic", return_value="mypyllant:heating"),
            patch.object(allocation, "_room_sensor_ids",
                         return_value={"101": "sensor.r1", "102": "sensor.r2"}),
            patch.object(allocation, "_fetch", fetch),
        ):
            result = asyncio.run(allocation.diagnose_unallocated(
                self.hass, self.main, days=1
            ))
        self.assertEqual(result["gas_kwh_in_valid_hours"], 2)
        self.assertEqual(result["unallocated_kwh"], 0)
        self.assertEqual(result["total_unallocated_hours"], 0)
        self.assertFalse(result["missing_room_breakdown"])

    def test_dry_run_writes_nothing(self):
        result=asyncio.run(self.run_case(self.snapshots(),dry_run=True))
        self.assertEqual(result["status"],"dry_run")
        self.assertFalse(self.writes)


if __name__=="__main__":
    unittest.main()
