"""Offline tests for tado X HOPS payloads; never connect to a heating system."""

import asyncio
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch


def fake_module(name, **members):
    mod = ModuleType(name)
    mod.__dict__.update(members)
    sys.modules.setdefault(name, mod)
    return sys.modules[name]


fake_module("homeassistant")
fake_module("homeassistant.exceptions", HomeAssistantError=type("HomeAssistantError", (Exception,), {}))
fake_module("homeassistant.helpers")
fake_module("homeassistant.helpers.update_coordinator",
            DataUpdateCoordinator=object,
            UpdateFailed=type("UpdateFailed", (Exception,), {}))

SOURCE=Path(__file__).resolve().parents[1]/"custom_components"/"tado"/"tadox_ext.py"
spec=importlib.util.spec_from_file_location("tadox_ext", SOURCE)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FakeCoordinator:
    is_x=True
    home_id=123
    zones=[{"id":101,"name":"Kitchen"}]
    _tado=object()

    async def _async_tado_call(self, fn, *args):
        return fn(*args)


def day_schedule():
    return [
        {"dayType":"MONDAY","start":"00:00","end":"06:00",
         "setting":{"power":"ON","temperature":{"value":18}}},
        {"dayType":"MONDAY","start":"06:00","end":"22:00",
         "setting":{"power":"ON","temperature":{"value":20}}},
        {"dayType":"MONDAY","start":"22:00",
         "setting":{"power":"ON","temperature":{"value":18}}},
    ]


class TadoXApiTests(unittest.TestCase):
    def test_parse_missing_last_end_preserves_full_day(self):
        canonical=module.canonical_day({"schedule":day_schedule()}, "MONDAY")
        self.assertEqual([b["start"] for b in canonical],[0,360,1320])
        self.assertEqual([b["end"] for b in canonical],[360,1320,1440])
        self.assertEqual(canonical[1]["temperature"],20)
        payload=module.make_day_payload("MONDAY",[
            {"start":"00:00","end":"06:00","power":"ON","temperature":18},
            {"start":"06:00","end":"22:00","power":"ON","temperature":20},
            {"start":"22:00","end":"24:00","power":"ON","temperature":18},
        ])
        self.assertEqual(module.canonical_day(payload,"MONDAY"),canonical)
        self.assertEqual(payload["daySchedule"][-1]["end"],"24:00")

    def test_reject_gaps_and_bad_setpoints(self):
        for blocks in [
            [{"start":"00:00","end":"23:59","power":"ON","temperature":20}],
            [{"start":"00:00","end":"24:00","power":"ON","temperature":35}],
            [{"start":"00:00","end":"12:00","power":"OFF","temperature":None},
             {"start":"13:00","end":"24:00","power":"ON","temperature":20}],
        ]:
            with self.subTest(blocks=blocks):
                with self.assertRaises(Exception):
                    module.make_day_payload("MONDAY",blocks)

    def test_save_rejects_stale_schedule_without_post(self):
        calls=[]
        def fake_request(client,home,method,endpoint,payload):
            calls.append((method,endpoint))
            return {"schedule":day_schedule()}
        async def run():
            api=module.TadoXClient(FakeCoordinator())
            with patch.object(module,"_request",fake_request):
                with self.assertRaisesRegex(Exception,"changed"):
                    await api.save_day(101,"MONDAY",[
                        {"start":"00:00","end":"24:00","power":"ON","temperature":20}
                    ],"0"*64)
        asyncio.run(run())
        self.assertEqual([x[0] for x in calls],["GET"])

    def test_save_verifies_readback(self):
        stored={"schedule":day_schedule()}
        calls=[]
        def fake_request(client,home,method,endpoint,payload):
            calls.append(method)
            if method=="POST":
                stored["schedule"]=payload["daySchedule"]
                return {}
            return stored
        async def run():
            api=module.TadoXClient(FakeCoordinator())
            before=module.schedule_signature(module.canonical_day(stored,"MONDAY"))
            blocks=[{"start":"00:00","end":"24:00",
                     "power":"ON","temperature":19.5}]
            with patch.object(module,"_request",fake_request):
                return await api.save_day(101,"MONDAY",blocks,before)
        r=asyncio.run(run())
        self.assertTrue(r["confirmed"])
        self.assertEqual(calls,["GET","POST","GET"])

    def test_flow_and_dhw_clamp(self):
        state={"setpoint":62,"setpointConstraints":{"min":35,"max":70}}
        flow={"maxFlowTemperature":55,
              "maxFlowTemperatureConstraints":{"min":20,"max":75},
              "autoAdaptation":{"enabled":True,"maxFlowTemperature":49}}
        writes=[]
        def fake_request(client,home,method,endpoint,payload):
            if method!="GET":writes.append((method,endpoint,payload))
            return state if "domesticHotWater" in endpoint else flow
        async def run():
            api=module.TadoXClient(FakeCoordinator())
            with patch.object(module,"_request",fake_request):
                with self.assertRaises(Exception):
                    await api.set_dhw(90)
                await api.set_dhw(60)
                await api.set_flow(max_temp=54,enabled=False)
        asyncio.run(run())
        self.assertEqual(writes[0][2],{"setpoint":60})
        self.assertEqual(writes[1][2],
                         {"maxFlowTemperature":54,"autoAdaptation":{"enabled":False}})


if __name__=="__main__":
    unittest.main()
