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
        self.hass=SimpleNamespace(data={},config=SimpleNamespace(time_zone="Europe/Brussels"))
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


    def test_calendar_day_keeps_both_repeated_dst_hours(self):
        # Brussels 25 October 2026 observes 02:00 twice: CEST and CET.
        from zoneinfo import ZoneInfo
        tz=ZoneInfo("Europe/Brussels")
        prior=datetime(2026,10,24,23,tzinfo=timezone.utc).timestamp()
        first=datetime(2026,10,25,0,tzinfo=timezone.utc).timestamp()
        second=datetime(2026,10,25,1,tzinfo=timezone.utc).timestamp()
        raw={
            allocation._stat_id(self.main,"101"):[
                {"start":prior,"sum":1000},
                {"start":first,"sum":2000},
                {"start":second,"sum":4000},
            ],
            allocation._stat_id(self.main,"102"):[
                {"start":prior,"sum":0},{"start":first,"sum":0},
                {"start":second,"sum":0},
            ],
            allocation._stat_id(self.main,"unallocated"):[
                {"start":prior,"sum":0},{"start":first,"sum":0},
                {"start":second,"sum":0},
            ]
        }
        async def fetch(*args, **kwargs):
            self.assertEqual(args[-1],"hour")
            return raw
        with patch.object(allocation,"_fetch",fetch):
            result=asyncio.run(allocation.allocation_history(
                self.hass,self.main,period="day",
                start_date="2026-10-25",end_date="2026-10-25"))
        self.assertEqual(result["aggregation"],"hour")
        values=[(row["period"],row.get("Kitchen",0)) for row in result["series"]
                if row.get("Kitchen",0)>0]
        self.assertEqual(len(values),2)
        self.assertEqual([x[1] for x in values],[1000,2000])
        self.assertNotEqual(values[0][0],values[1][0])
        self.assertIn("+02:00",values[0][0])
        self.assertIn("+01:00",values[1][0])

    def test_calendar_month_filters_only_requested_dates(self):
        from zoneinfo import ZoneInfo
        tz=ZoneInfo("Europe/Brussels")
        def stamp(day):
            return datetime(2025,11,day,0,tzinfo=tz).timestamp()
        raw={
            allocation._stat_id(self.main,"101"):[
                {"start":stamp(1),"sum":100},
                {"start":stamp(2),"sum":101},
                {"start":stamp(3),"sum":104},
                {"start":stamp(4),"sum":106},
                {"start":stamp(5),"sum":108},
            ],
            allocation._stat_id(self.main,"102"):[],
            allocation._stat_id(self.main,"unallocated"):[],
        }
        async def fetch(*args,**kwargs):
            return raw
        with patch.object(allocation,"_fetch",fetch):
            result=asyncio.run(allocation.allocation_history(
                self.hass,self.main,period="month",
                start_date="2025-11-02",end_date="2025-11-03"))
        self.assertEqual(result["range_start"],"2025-11-02")
        self.assertEqual(result["range_end"],"2025-11-03")
        self.assertEqual(result["aggregation"],"day")
        self.assertEqual([x["period"] for x in result["series"]],
                         ["2025-11-02","2025-11-03"])
        self.assertEqual(sum(row["Kitchen"] for row in result["series"]),4)

    def test_year_uses_monthly_rows_not_three_year_hourly_query(self):
        from zoneinfo import ZoneInfo
        tz=ZoneInfo("Europe/Brussels")
        def month(y,m):
            return datetime(y,m,1,0,tzinfo=tz).timestamp()
        raw={
            allocation._stat_id(self.main,"101"):[
                {"start":month(2024,12),"sum":10},
                {"start":month(2025,1),"sum":13},
                {"start":month(2025,2),"sum":17},
                {"start":month(2025,3),"sum":20},
            ]
        }
        queried=[]
        async def fetch(*args,**kwargs):
            queried.append(args[-1])
            return raw
        with patch.object(allocation,"_fetch",fetch):
            result=asyncio.run(allocation.allocation_history(
                self.hass,self.main,period="year",
                start_date="2025-01-01",end_date="2025-12-31"))
        self.assertEqual(queried,["month"])
        self.assertEqual(result["aggregation"],"month")
        self.assertEqual([x["period"] for x in result["series"]],
                         ["2025-01","2025-02","2025-03"])
        self.assertEqual([x["Kitchen"] for x in result["series"]],[3,4,3])

    def test_custom_long_period_exact_partial_month_edges(self):
        from zoneinfo import ZoneInfo
        tz=ZoneInfo("Europe/Brussels")
        def stamp(month,day):
            return datetime(2025,month,day,0,tzinfo=tz).timestamp()
        monthly={allocation._stat_id(self.main,"101"):[
            {"start":stamp(m,1),"sum":m*100} for m in range(1,8)]}
        hourly={allocation._stat_id(self.main,"101"):[
            {"start":datetime(2025,1,9,23,tzinfo=tz).timestamp(),"sum":0},
            {"start":stamp(1,10),"sum":5},
            {"start":datetime(2025,6,30,23,tzinfo=tz).timestamp(),"sum":5},
            {"start":stamp(7,1),"sum":8},
        ]}
        queried=[]
        async def fetch(hass,start,end,ids,period="hour"):
            queried.append((period,start,end))
            if period=="month":return monthly
            # Include only the requested local month/edge, plus the preceding
            # baseline row used for the first delta.
            return {key:[r for r in rows if
                        (start-timedelta(hours=1)).timestamp()<=r["start"]<end.timestamp()]
                    for key,rows in hourly.items()}
        with patch.object(allocation,"_fetch",fetch):
            result=asyncio.run(allocation.allocation_history(
                self.hass,self.main,period="custom",
                start_date="2025-01-10",end_date="2025-07-20"))
        self.assertEqual(result["aggregation"],"month")
        self.assertEqual([q[0] for q in queried],["month","hour","hour"])
        self.assertIn("2025-01", [r["period"] for r in result["series"]])
        self.assertIn("2025-07", [r["period"] for r in result["series"]])

    def test_dry_run_writes_nothing(self):
        result=asyncio.run(self.run_case(self.snapshots(),dry_run=True))
        self.assertEqual(result["status"],"dry_run")
        self.assertFalse(self.writes)


if __name__=="__main__":
    unittest.main()
