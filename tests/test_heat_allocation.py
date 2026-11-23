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


    def test_hourly_quality_scan_finds_first_realistic_day_without_writing(self):
        """Flat historical days lead to a complete, sustained varied run."""
        from datetime import date, time
        from zoneinfo import ZoneInfo

        class FrozenDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                fixed = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)
                return fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None)

        tz = ZoneInfo("Europe/Brussels")
        self.hass.config = SimpleNamespace(time_zone="Europe/Brussels")
        first = date(2026, 11, 3)
        end = date(2026, 11, 10)
        def utc_midnight(d):
            return datetime.combine(d, time.min, tzinfo=tz).astimezone(timezone.utc)
        hour = utc_midnight(first) - timedelta(hours=1)
        end_hour = utc_midnight(end)
        values = []
        running = 0.0
        while hour < end_hour:
            local = hour.astimezone(tz)
            day_index = (local.date() - first).days
            # November 3-6 are flat-positive; Nov 7-9 have real hourly variety.
            amount = 100 if day_index < 4 else (60 + local.hour * 5)
            running += amount
            values.append({"start": hour.timestamp(), "sum": running})
            hour += timedelta(hours=1)

        async def fetch(*args, **kwargs):
            return {"vaillant:hourly": values}

        with (
            patch.object(allocation, "datetime", FrozenDateTime),
            patch.object(allocation, "_gas_statistic", return_value="vaillant:hourly"),
            patch.object(allocation, "_fetch", fetch),
            patch.object(
                allocation, "async_add_external_statistics",
                side_effect=AssertionError("Scan must be read-only")
            ),
        ):
            result = asyncio.run(allocation.detect_vaillant_hourly_start(
                self.hass, days=7, confirmation_days=3,
                tolerance_wh=1.0
            ))
        self.assertEqual(result["status"], "hourly_uniformity_scan_completed")
        self.assertTrue(result["read_only"])
        self.assertTrue(result["no_statistics_modified"])
        self.assertEqual(result["first_complete_nonuniform_day"], "2026-11-07")
        self.assertEqual(result["first_consecutive_nonuniform_day"], "2026-11-07")
        self.assertEqual(result["last_uniform_positive_day"], "2026-11-06")
        self.assertEqual(result["candidate_cutoff_day"], "2026-11-07")
        self.assertFalse(result["candidate_is_proven_measured_hourly"])
        self.assertEqual(
            result["classification_counts"]["uniform_positive_suspected_backfill"], 4
        )
        self.assertEqual(result["classification_counts"]["nonuniform"], 3)
        self.assertEqual(len(result["transition_window"]), 7)

    def test_hourly_quality_scan_handles_dst_and_missing_hours(self):
        """DST fall-back day requires 25 genuine hourly samples, not 24."""
        from datetime import date, time
        from zoneinfo import ZoneInfo

        class FrozenDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                fixed = datetime(2026, 10, 29, 12, tzinfo=timezone.utc)
                return fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None)

        tz = ZoneInfo("Europe/Brussels")
        self.hass.config = SimpleNamespace(time_zone="Europe/Brussels")
        first = date(2026, 10, 19)
        end = date(2026, 10, 29)
        def midnight(d):
            return datetime.combine(d, time.min, tzinfo=tz).astimezone(timezone.utc)
        hour = midnight(first) - timedelta(hours=1)
        end_hour = midnight(end)
        running = 0.0
        rows = []
        while hour < end_hour:
            local = hour.astimezone(tz)
            day_index = (local.date() - first).days
            # All positive flat up to 24th. Oct 25 (25h) and thereafter varied.
            amount = 100 if day_index < 6 else (55 + int(hour.timestamp()/3600)%24*4)
            running += amount
            rows.append({"start": hour.timestamp(), "sum": running})
            hour += timedelta(hours=1)
        # Missing one source hour on the last complete day cannot look reliable.
        missing_stamp = (midnight(date(2026, 10, 28))
                         + timedelta(hours=14)).timestamp()
        rows = [r for r in rows if r["start"] != missing_stamp]
        async def fetch(*args, **kwargs):
            return {"vaillant:hourly": rows}

        with (
            patch.object(allocation, "datetime", FrozenDateTime),
            patch.object(allocation, "_gas_statistic", return_value="vaillant:hourly"),
            patch.object(allocation, "_fetch", fetch),
        ):
            result = asyncio.run(allocation.detect_vaillant_hourly_start(
                self.hass, days=10, confirmation_days=3
            ))
        self.assertEqual(result["candidate_cutoff_day"], "2026-10-25")
        self.assertEqual(result["first_complete_nonuniform_day"], "2026-10-25")
        self.assertEqual(result["classification_counts"]["incomplete"], 1)
        autumn = next(
            row for row in result["transition_window"]
            if row["date"] == "2026-10-25"
        )
        self.assertEqual(autumn["expected_hours"], 25)
        self.assertEqual(autumn["valid_hours"], 25)
        self.assertEqual(autumn["classification"], "nonuniform")

    def test_hourly_quality_scan_distinguishes_zero_from_uniform_positive(self):
        from datetime import date, time
        from zoneinfo import ZoneInfo

        class FrozenDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                fixed = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)
                return fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None)

        tz = ZoneInfo("Europe/Brussels")
        self.hass.config = SimpleNamespace(time_zone="Europe/Brussels")
        day0 = date(2026, 11, 7)
        def midnight(d):
            return datetime.combine(d, time.min, tzinfo=tz).astimezone(timezone.utc)
        hour = midnight(day0)-timedelta(hours=1)
        end = midnight(date(2026, 11, 10))
        total = 0.
        rows = []
        while hour < end:
            # First day no gas, second uniform, third varied.
            d = hour.astimezone(tz).date()
            amount = (0 if d <= day0 else
                      300 if d == date(2026, 11, 8) else
                      100 + hour.astimezone(tz).hour*10)
            total += amount
            rows.append({"start": hour.timestamp(), "sum": total})
            hour += timedelta(hours=1)
        async def fetch(*args, **kwargs):
            return {"vaillant:hourly": rows}

        with (
            patch.object(allocation, "datetime", FrozenDateTime),
            patch.object(allocation, "_gas_statistic", return_value="vaillant:hourly"),
            patch.object(allocation, "_fetch", fetch),
        ):
            report = asyncio.run(allocation.detect_vaillant_hourly_start(
                self.hass, days=3, confirmation_days=2
            ))
        self.assertEqual(report["classification_counts"]["no_heating"], 1)
        self.assertEqual(report["classification_counts"]["uniform_positive_suspected_backfill"], 1)
        self.assertEqual(report["first_complete_nonuniform_day"], "2026-11-09")
        self.assertIsNone(report["candidate_cutoff_day"])


    def test_confirmed_cutoff_previews_then_deletes_only_tado_v2_and_rebuilds(self):
        """Confirmed migration must be strictly household-scoped and rebase sums."""
        from zoneinfo import ZoneInfo
        self.hass.config = SimpleNamespace(time_zone="Europe/Brussels")
        local = datetime.now(ZoneInfo("Europe/Brussels"))
        day = (local.date() - timedelta(days=1))
        cutoff = datetime(
            day.year, day.month, day.day, tzinfo=ZoneInfo("Europe/Brussels")
        ).astimezone(timezone.utc)
        end = datetime.now(timezone.utc).replace(
            minute=0, second=0, microsecond=0
        )
        count = int((end - cutoff).total_seconds() // 3600)
        source = [
            {"start": (cutoff - timedelta(hours=1)).timestamp(), "sum": 1000}
        ]
        r1, r2 = [], []
        for i in range(count):
            t = (cutoff+timedelta(hours=i)).timestamp()
            source.append({"start": t, "sum": 1100 + 100*i})
            r1.append({"start": t, "mean": 100})
            r2.append({"start": t, "mean": 0})
        raw = {
            "mypyllant:heating": source,
            "sensor.r1": r1,
            "sensor.r2": r2,
        }
        saved = {}
        removals = []
        writes = []
        config_changes = []
        def update_entry(entry, *, options):
            entry.options = options
            config_changes.append(dict(options))
        self.hass.config_entries = SimpleNamespace(async_update_entry=update_entry)

        class FakeRecorder:
            def async_clear_statistics(self, ids, *, start_time, end_time, on_done):
                removals.append((ids, start_time, end_time))
                on_done()
            async def async_block_till_done(self):
                return None

        async def fetch(hass, start, end_time, ids, period="hour"):
            if "mypyllant:heating" in ids:
                return raw
            if end_time <= cutoff:
                return {}
            return saved

        def add_stats(hass, meta, rows):
            writes.append((meta, rows))
            saved[meta["statistic_id"]] = [
                dict(r, start=r["start"].timestamp()) for r in rows
            ]
        async def run_case(dry_run, confirm=False):
            self.hass.loop = asyncio.get_running_loop()
            return await allocation.configure_heating_allocation_cutoff(
                self.hass, self.main, date=day.isoformat(),
                dry_run=dry_run, confirm_delete_pre_cutoff=confirm,
            )

        with (
            patch.object(allocation, "_gas_statistic", return_value="mypyllant:heating"),
            patch.object(allocation, "_room_sensor_ids",
                         return_value={"101":"sensor.r1","102":"sensor.r2"}),
            patch.object(allocation, "_capacities",
                         return_value={"101":1.0,"102":1.0}),
            patch.object(allocation, "_fetch", fetch),
            patch.object(allocation, "get_instance", return_value=FakeRecorder()),
            patch.object(allocation, "async_add_external_statistics", add_stats),
        ):
            preview = asyncio.run(run_case(True))
            self.assertEqual(preview["status"], "cutoff_preview")
            self.assertEqual(preview["target_statistic_count"], 3)
            self.assertEqual(preview["retained_hours_per_statistic"], count)
            self.assertEqual(preview["retained_statistic_rows_to_rebuild"], count*3)
            self.assertFalse(removals)
            self.assertFalse(writes)
            self.assertFalse(config_changes)
            with self.assertRaisesRegex(Exception, "confirm_delete_pre_cutoff"):
                asyncio.run(run_case(False, confirm=False))
            self.assertFalse(removals)
            result = asyncio.run(run_case(False, confirm=True))
        self.assertEqual(result["status"], "cutoff_applied")
        self.assertFalse(result["migration_pending"])
        self.assertEqual(len(removals), 1)
        self.assertEqual(set(removals[0][0]), {
            allocation._stat_id(self.main,z) for z in ("101","102","unallocated")
        })
        self.assertNotIn("mypyllant:heating", removals[0][0])
        self.assertEqual(removals[0][2], cutoff)
        self.assertEqual(len(writes), 3)
        self.assertAlmostEqual(
            saved[allocation._stat_id(self.main,"101")][-1]["sum"], count*0.1
        )
        self.assertAlmostEqual(
            saved[allocation._stat_id(self.main,"102")][-1]["sum"], 0
        )
        self.assertEqual(config_changes[-1][allocation.CUTOFF_COMPLETE_OPTION], True)
        self.assertEqual(
            allocation._allocation_cutoff(self.main), cutoff
        )

    def test_cutoff_missing_source_aborts_without_side_effects(self):
        """No old rows may be deleted when a retained source hour is missing."""
        from zoneinfo import ZoneInfo
        self.hass.config = SimpleNamespace(time_zone="Europe/Brussels")
        local = datetime.now(ZoneInfo("Europe/Brussels"))
        day = local.date() - timedelta(days=1)
        cutoff = datetime(
            day.year, day.month, day.day, tzinfo=ZoneInfo("Europe/Brussels")
        ).astimezone(timezone.utc)
        source = [{
            "start": (cutoff-timedelta(hours=1)).timestamp(), "sum": 1000
        }]
        async def fetch(*args, **kwargs):
            return {"mypyllant:heating": source}
        with (
            patch.object(allocation, "_gas_statistic", return_value="mypyllant:heating"),
            patch.object(allocation, "_room_sensor_ids",
                         return_value={"101":"sensor.r1","102":"sensor.r2"}),
            patch.object(allocation, "_capacities",
                         return_value={"101":1.0,"102":1.0}),
            patch.object(allocation, "_fetch", fetch),
            patch.object(allocation, "get_instance",
                         side_effect=AssertionError("no Recorder deletion")),
            patch.object(allocation, "async_add_external_statistics",
                         side_effect=AssertionError("no derived statistics edits")),
        ):
            report = asyncio.run(allocation.configure_heating_allocation_cutoff(
                self.hass, self.main, date=day.isoformat(),
                dry_run=False, confirm_delete_pre_cutoff=True,
            ))
        self.assertEqual(report["status"], "blocked_missing_or_invalid_vaillant_hours")
        self.assertTrue(report["no_statistics_modified"])

    def test_cutoff_clips_history_and_blocks_older_reconciliation(self):
        self.hass.config = SimpleNamespace(time_zone="Europe/Brussels")
        self.main.config_entry.options[allocation.CUTOFF_OPTION] = (
            "2026-11-02T23:00:00+00:00"
        )
        self.main.config_entry.options[allocation.CUTOFF_COMPLETE_OPTION] = True
        captured = []
        async def live(hass, main, start, end, period, group, tz):
            captured.append((start, end, period))
            return {"period":period,"series":[],"data_mode":"live_reconciled"}
        with patch.object(allocation, "_live_reconciled_history", live):
            result = asyncio.run(allocation.allocation_history(
                self.hass, self.main, period="month",
                start_time="2026-10-15T00:00:00+02:00",
                end_time="2026-11-05T00:00:00+01:00",
            ))
            ignored = asyncio.run(allocation.reconciliation_report(
                self.hass, self.main, date="2026-11-02"
            ))
        self.assertEqual(result["data_mode"], "live_reconciled")
        self.assertEqual(captured[0][0].isoformat(), "2026-11-02T23:00:00+00:00")
        self.assertEqual(ignored["status"], "before_allocation_cutoff")
        self.assertEqual(len(captured), 1)
        earlier = asyncio.run(allocation.allocation_history(
            self.hass, self.main, period="day",
            start_time="2026-10-31T00:00:00+01:00",
            end_time="2026-11-02T00:00:00+01:00",
        ))
        self.assertEqual(earlier["data_mode"], "no_data_before_cutoff")
        self.assertEqual(earlier["series"], [])

    def test_pending_cutoff_disables_hourly_writes(self):
        self.main.config_entry.options[allocation.CUTOFF_OPTION] = (
            "2026-11-02T23:00:00+00:00"
        )
        self.main.config_entry.options[allocation.CUTOFF_COMPLETE_OPTION] = False
        with patch.object(allocation, "async_add_external_statistics",
                          side_effect=AssertionError("migration not finished")):
            result = asyncio.run(allocation.allocate_recent(
                self.hass, self.main, days=3
            ))
        self.assertEqual(result["status"], "allocation_cutoff_cleanup_pending")
        self.assertTrue(result["no_statistics_modified"])


if __name__=="__main__":
    unittest.main()
