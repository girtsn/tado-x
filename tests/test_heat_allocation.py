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


    def test_recent_history_reconciles_against_updated_source_without_writes(self):
        """A source value revised after v2 publication must win in the UI."""
        self.hass.config = SimpleNamespace(time_zone="Europe/Brussels")
        older = (self.end - timedelta(hours=3)).timestamp()
        raw = {
            "mypyllant:heating": [
                {"start": older, "sum": 1000},
                {"start": self.t0, "sum": 3000},
                {"start": self.t1, "sum": 5000},
            ],
            "sensor.r1": [
                {"start": self.t0, "mean": 25},
                {"start": self.t1, "mean": 50},
            ],
            "sensor.r2": [
                {"start": self.t0, "mean": 75},
                {"start": self.t1, "mean": 50},
            ],
        }
        for zid in ("101", "102", "unallocated"):
            statistic_id = allocation._stat_id(self.main, zid)
            raw[statistic_id] = [
                {"start": older, "sum": 0},
                {"start": self.t0, "sum": 0.25},
                {"start": self.t1, "sum": 0.50},
            ] if zid != "unallocated" else [
                {"start": older, "sum": 0},
                {"start": self.t0, "sum": 0},
                {"start": self.t1, "sum": 0},
            ]
        async def fetch(*args, **kwargs):
            return raw
        with (
            patch.object(allocation, "_gas_statistic", return_value="mypyllant:heating"),
            patch.object(allocation, "_room_sensor_ids",
                         return_value={"101": "sensor.r1", "102": "sensor.r2"}),
            patch.object(allocation, "_capacities",
                         return_value={"101": 1.0, "102": 1.0}),
            patch.object(allocation, "_fetch", fetch),
            patch.object(allocation, "async_add_external_statistics",
                         side_effect=AssertionError("Read-only call must never write")),
        ):
            result = asyncio.run(allocation.allocation_history(
                self.hass, self.main, period="day",
                start_time=datetime.fromtimestamp(self.t0,timezone.utc).isoformat(),
                end_time=self.end.isoformat(),
            ))
        self.assertEqual(result["data_mode"], "live_reconciled")
        self.assertEqual(result["vaillant_heating_kwh"], 4.0)
        self.assertEqual(result["allocated_kwh"], 4.0)
        self.assertEqual(result["unallocated_kwh"], 0)
        self.assertEqual(result["legacy_stored_kwh"], 1.0)
        self.assertEqual(result["legacy_difference_kwh"], 3.0)
        self.assertEqual(result["stale_stored_hours"], 2)
        self.assertEqual(result["source_hours"], 2)
        self.assertEqual(result["missing_source_hours"], 0)
        total = sum(sum(float(r.get(room, 0)) for room in result["rooms"])
                    for r in result["series"])
        self.assertAlmostEqual(total, 4.0, places=2)

    def test_reconciliation_uses_home_assistant_day_and_dst(self):
        self.hass.config = SimpleNamespace(time_zone="Europe/Brussels")
        spans = []
        async def live(hass, main, start, end, period, group, tz):
            spans.append((start, end, period, group, str(tz)))
            return {"read_only": True}
        with patch.object(allocation, "_live_reconciled_history", live):
            a = asyncio.run(allocation.reconciliation_report(
                self.hass, self.main, date="2026-03-29"
            ))
            b = asyncio.run(allocation.reconciliation_report(
                self.hass, self.main, date="2026-10-25"
            ))
        self.assertEqual(a["status"], "reconciliation_completed")
        self.assertEqual(b["date"], "2026-10-25")
        self.assertEqual((spans[0][1]-spans[0][0]).total_seconds(), 23*3600)
        self.assertEqual((spans[1][1]-spans[1][0]).total_seconds(), 25*3600)
        self.assertEqual(spans[0][0].isoformat(), "2026-03-28T23:00:00+00:00")
        self.assertEqual(spans[1][0].isoformat(), "2026-10-24T22:00:00+00:00")



    def test_rebuild_corrects_all_old_hours_and_cumulative_sums(self):
        """Late Vaillant revisions must upsert old v2 rows and rebase successors."""
        older = (self.end - timedelta(hours=3)).timestamp()
        raw = {
            "mypyllant:heating": [
                {"start": older, "sum": 1000},
                {"start": self.t0, "sum": 3000},
                {"start": self.t1, "sum": 5000},
            ],
            "sensor.r1": [
                {"start": self.t0, "mean": 25},
                {"start": self.t1, "mean": 50},
            ],
            "sensor.r2": [
                {"start": self.t0, "mean": 75},
                {"start": self.t1, "mean": 50},
            ],
        }
        # Older v2 inputs were too small, but both old timestamps exist.
        for zid, amounts in (("101", [(0.25, 0.25), (0.25, 0.5)]),
                             ("102", [(0.75, 0.75), (0.75, 1.5)]),
                             ("unallocated", [(0, 0), (0, 0)])):
            raw[allocation._stat_id(self.main, zid)] = [
                {"start": stamp, "state": st, "sum": total}
                for stamp, (st, total) in zip((self.t0, self.t1), amounts)
            ]
        async def fetch(*args, **kwargs):
            return raw
        with (
            patch.object(allocation, "_gas_statistic", return_value="mypyllant:heating"),
            patch.object(allocation, "_room_sensor_ids",
                         return_value={"101": "sensor.r1", "102": "sensor.r2"}),
            patch.object(allocation, "_capacities",
                         return_value={"101": 1.0, "102": 1.0}),
            patch.object(allocation, "_fetch", fetch),
            patch.object(allocation, "async_add_external_statistics",
                         lambda hass, meta, rows: self.writes.append((meta, rows))),
        ):
            preview = asyncio.run(allocation.allocate_recent(
                self.hass, self.main, days=1, dry_run=True
            ))
            self.assertEqual(preview["status"], "dry_run")
            self.assertEqual(preview["changed_hours"], 2)
            self.assertEqual(preview["changed_statistic_rows"], 4)
            self.assertFalse(self.writes)
            result = asyncio.run(allocation.allocate_recent(
                self.hass, self.main, days=1, dry_run=False
            ))
        self.assertEqual(result["status"], "reconciled_hours_queued")
        self.assertEqual(result["gas_heating_kwh"], 4)
        self.assertEqual(result["changed_hours"], 2)
        corrections = {meta["statistic_id"]: rows for meta, rows in self.writes}
        bedroom = corrections[allocation._stat_id(self.main, "101")]
        bath = corrections[allocation._stat_id(self.main, "102")]
        self.assertEqual(len(bedroom), 2)
        self.assertAlmostEqual(bedroom[0]["state"], 0.5)
        self.assertAlmostEqual(bedroom[0]["sum"], 0.5)
        self.assertAlmostEqual(bedroom[1]["state"], 1.0)
        self.assertAlmostEqual(bedroom[1]["sum"], 1.5)
        self.assertAlmostEqual(bath[0]["sum"], 1.5)
        self.assertAlmostEqual(bath[1]["sum"], 2.5)

    def test_rebuild_refuses_to_break_cumulative_sums_across_missing_hour(self):
        """No partial rewrite when a later archived hour exists beyond source gap."""
        older = (self.end - timedelta(hours=3)).timestamp()
        raw = {
            "mypyllant:heating": [
                {"start": older, "sum": 1000},
                {"start": self.t0, "sum": 3000},
                # t1 is currently unavailable
            ],
            "sensor.r1": [{"start": self.t0, "mean": 50}],
            "sensor.r2": [{"start": self.t0, "mean": 50}],
        }
        for zid in ("101", "102", "unallocated"):
            raw[allocation._stat_id(self.main, zid)] = [
                {"start": self.t0, "state": 0.1, "sum": 0.1},
                {"start": self.t1, "state": 0.1, "sum": 0.2},
            ]
        async def fetch(*args, **kwargs):
            return raw
        with (
            patch.object(allocation, "_gas_statistic", return_value="mypyllant:heating"),
            patch.object(allocation, "_room_sensor_ids",
                         return_value={"101": "sensor.r1", "102": "sensor.r2"}),
            patch.object(allocation, "_capacities",
                         return_value={"101": 1.0, "102": 1.0}),
            patch.object(allocation, "_fetch", fetch),
            patch.object(allocation, "async_add_external_statistics",
                         side_effect=AssertionError("must not write partial history")),
        ):
            result = asyncio.run(allocation.allocate_recent(
                self.hass, self.main, days=1, dry_run=False
            ))
        self.assertEqual(result["status"], "blocked_missing_published_source_hour")
        self.assertTrue(result["no_statistics_modified"])

    def test_rebuild_unchanged_rows_are_not_reimported(self):
        older = (self.end - timedelta(hours=3)).timestamp()
        raw = {
            "mypyllant:heating": [
                {"start": older, "sum": 1000},
                {"start": self.t0, "sum": 3000},
                {"start": self.t1, "sum": 5000},
            ],
            "sensor.r1": [
                {"start": self.t0, "mean": 25},
                {"start": self.t1, "mean": 50},
            ],
            "sensor.r2": [
                {"start": self.t0, "mean": 75},
                {"start": self.t1, "mean": 50},
            ],
            allocation._stat_id(self.main, "101"): [
                {"start": self.t0, "state": 0.5, "sum": 0.5},
                {"start": self.t1, "state": 1.0, "sum": 1.5},
            ],
            allocation._stat_id(self.main, "102"): [
                {"start": self.t0, "state": 1.5, "sum": 1.5},
                {"start": self.t1, "state": 1.0, "sum": 2.5},
            ],
            allocation._stat_id(self.main, "unallocated"): [
                {"start": self.t0, "state": 0, "sum": 0},
                {"start": self.t1, "state": 0, "sum": 0},
            ],
        }
        async def fetch(*args, **kwargs):
            return raw
        with (
            patch.object(allocation, "_gas_statistic", return_value="mypyllant:heating"),
            patch.object(allocation, "_room_sensor_ids",
                         return_value={"101": "sensor.r1", "102": "sensor.r2"}),
            patch.object(allocation, "_capacities",
                         return_value={"101": 1.0, "102": 1.0}),
            patch.object(allocation, "_fetch", fetch),
            patch.object(allocation, "async_add_external_statistics",
                         side_effect=AssertionError("already correct")),
        ):
            result = asyncio.run(allocation.allocate_recent(
                self.hass, self.main, days=1, dry_run=False
            ))
        self.assertEqual(result["status"], "already_reconciled")
        self.assertEqual(result["changed_statistic_rows"], 0)


if __name__=="__main__":
    unittest.main()
