"""Offline tests of estimated gas-input allocation; no Home Assistant/boiler calls."""

import asyncio
import importlib.util
from dataclasses import dataclass
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


@dataclass
class FakeStat:
    start: datetime
    state: float
    sum: float


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
spec=importlib.util.spec_from_file_location("heat_allocation",SOURCE)
allocation=importlib.util.module_from_spec(spec);spec.loader.exec_module(allocation)


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
        by_name={meta["statistic_id"]:rows[0].state
                 for meta,rows in self.writes}
        self.assertAlmostEqual(by_name[allocation._stat_id(self.main,"101")],.5)
        self.assertAlmostEqual(by_name[allocation._stat_id(self.main,"102")],1.5)

    def test_missing_room_history_is_unallocated(self):
        result=asyncio.run(self.run_case(self.snapshots(room2_mean=None)))
        self.assertEqual(result["allocated_kwh"],0)
        self.assertEqual(result["unallocated_kwh"],2)
        by_name={meta["statistic_id"]:rows[0].state
                 for meta,rows in self.writes}
        self.assertAlmostEqual(by_name[allocation._stat_id(self.main,"unallocated")],2)

    def test_dry_run_writes_nothing(self):
        result=asyncio.run(self.run_case(self.snapshots(),dry_run=True))
        self.assertEqual(result["status"],"dry_run")
        self.assertFalse(self.writes)


if __name__=="__main__":
    unittest.main()
