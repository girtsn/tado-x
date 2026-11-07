"""Offline tests for restart-safe Eco/Top Boost and local mode status."""

import asyncio
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch


def stub(name, **attrs):
    m = sys.modules.setdefault(name, ModuleType(name))
    for key, value in attrs.items():
        setattr(m, key, value)
    return m


class HAError(Exception):
    pass


stub("homeassistant", __path__=[])
stub("homeassistant.exceptions", HomeAssistantError=HAError)
stub("homeassistant.helpers", __path__=[])
stub("homeassistant.helpers.event",
     async_track_point_in_utc_time=lambda *args: lambda: None)
stub("homeassistant.helpers.storage", Store=object)
stub("custom_components", __path__=[])
stub("custom_components.tado", __path__=[])

package = "custom_components.tado"
stub(package + ".tadox_ext", TadoXClient=lambda c: None)
source = (
    Path(__file__).resolve().parents[1] / "custom_components"
    / "tado" / "heating_modes.py"
)
spec = importlib.util.spec_from_file_location(package + ".heating_modes", source)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class FakeStore:
    def __init__(self):
        self.saved = None
        self.writes = []

    async def async_load(self):
        return dict(self.saved) if self.saved is not None else None

    async def async_save(self, state):
        self.saved = dict(state)
        self.writes.append(dict(state))


class FakeHass:
    def async_create_task(self, coroutine):
        return asyncio.create_task(coroutine)


class FakeCoordinator:
    is_x = True
    home_id = 123
    x_settings = None

    def __init__(self):
        self.notified = 0
        self.post_action_polls_scheduled = 0

    def schedule_post_action_room_refresh(self):
        self.post_action_polls_scheduled += 1

    def async_update_listeners(self):
        self.notified += 1


class FakeScheduler:
    def __init__(self):
        self.callbacks = []
        self.cancellations = 0

    def __call__(self, hass, callback, deadline):
        record = {"callback": callback, "deadline": deadline, "active": True}
        self.callbacks.append(record)

        def cancel():
            record["active"] = False
            self.cancellations += 1

        return cancel


class FakeClient:
    def __init__(self):
        self.flow_enabled = True
        self.calls = []
        self.fail_resume = False
        self.fail_boost = False
        self.fail_flow_get = False

    async def get_flow(self):
        self.calls.append("get_flow")
        if self.fail_flow_get:
            raise HAError("flow unavailable")
        return {"autoAdaptation": {"enabled": self.flow_enabled}}

    async def set_flow(self, *, enabled=None, max_temp=None):
        self.calls.append(("set_flow", enabled))
        if enabled is not None:
            self.flow_enabled = enabled
        return await self.get_flow()

    async def heating_quick_action(self, action):
        self.calls.append(("quick_action", action))
        if action == "resume" and self.fail_resume:
            raise HAError("resume unavailable")
        if action == "boost" and self.fail_boost:
            raise HAError("boost unavailable")
        return {"accepted": True}


class HeatingModeTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)
        self.store = FakeStore()
        self.hass = FakeHass()
        self.coord = FakeCoordinator()
        self.scheduler = FakeScheduler()
        self.client = FakeClient()
        self.original_client = module.TadoXClient
        module.TadoXClient = lambda coordinator: self.client
        self.clock = patch.object(module, "utcnow", return_value=self.now)
        self.clock.start()

    def tearDown(self):
        self.clock.stop()
        module.TadoXClient = self.original_client

    async def manager(self):
        instance = module.HeatingModeManager(
            self.hass, self.coord, store=self.store, schedule=self.scheduler
        )
        await instance.async_start()
        return instance

    def test_eco_boost_persisted_and_recovers_after_restart(self):
        async def exercise():
            m = await self.manager()
            result = await m.async_action("eco_boost")
            self.assertEqual(result["mode"], "eco_boost")
            self.assertEqual(m.status()["mode_label"], "Eco Boost")
            self.assertEqual(self.store.saved["mode"], "eco_boost")
            self.assertEqual(self.store.saved["kind"], "resume_and_adapt")
            self.assertTrue(self.client.flow_enabled)
            self.assertEqual(
                self.store.saved["due"],
                (self.now + timedelta(minutes=30)).isoformat(),
            )
            self.assertEqual(
                [c for c in self.client.calls if isinstance(c, tuple)],
                [("quick_action", "boost")],
            )
            m.async_stop()
            self.assertFalse(self.scheduler.callbacks[-1]["active"])
            restarted = await self.manager()
            self.assertEqual(restarted.status()["mode"], "eco_boost")
            with patch.object(module, "utcnow", return_value=self.now + timedelta(minutes=31)):
                await restarted.async_recover()
            self.assertEqual(restarted.status()["mode"], "schedule")
            self.assertFalse(restarted.status()["pending"])
            self.assertEqual(self.store.saved["mode"], "schedule")
            self.assertEqual(self.store.saved["kind"], None)
            self.assertIn(("quick_action", "resume"), self.client.calls)
            self.assertTrue(self.coord.notified > 0)

        asyncio.run(exercise())

    def test_top_boost_disables_adaptation_then_restores_after_restart(self):
        async def exercise():
            m = await self.manager()
            await m.async_action("top_boost")
            self.assertFalse(self.client.flow_enabled)
            self.assertEqual(m.status()["mode_label"], "Top Boost")
            self.assertEqual(self.store.saved["kind"], "resume_and_adapt")
            self.assertEqual(
                [c for c in self.client.calls if isinstance(c, tuple)],
                [("set_flow", False), ("quick_action", "boost")],
            )
            m.async_stop()
            restarted = await self.manager()
            with patch.object(module, "utcnow", return_value=self.now + timedelta(minutes=31)):
                await restarted.async_recover()
            self.assertTrue(self.client.flow_enabled)
            self.assertEqual(restarted.status()["mode"], "schedule")
            self.assertIn(("set_flow", True), self.client.calls)
            self.assertEqual(self.store.saved["kind"], None)

        asyncio.run(exercise())

    def test_heating_off_supersedes_pending_boost_without_auto_resume(self):
        async def exercise():
            m = await self.manager()
            await m.async_action("top_boost")
            await m.async_action("off")
            self.assertTrue(self.client.flow_enabled)
            self.assertEqual(m.status()["mode"], "off")
            self.assertEqual(self.store.saved["kind"], None)
            before = len(self.client.calls)
            with patch.object(module, "utcnow", return_value=self.now + timedelta(hours=1)):
                await m.async_recover()
            self.assertEqual(len(self.client.calls), before)
            m.async_stop()
            reloaded = await self.manager()
            self.assertEqual(reloaded.status()["mode"], "off")
            self.assertIsNone(reloaded.status()["due_utc"])

        asyncio.run(exercise())

    def test_resume_reenables_adaptation_and_cancels_timer(self):
        async def exercise():
            m = await self.manager()
            await m.async_action("top_boost")
            result = await m.async_action("resume")
            self.assertTrue(result["flow_adaptation_ensured_enabled"])
            self.assertTrue(self.client.flow_enabled)
            self.assertFalse(m.status()["pending"])
            self.assertEqual(m.status()["mode"], "schedule")

        asyncio.run(exercise())

    def test_each_heating_action_queues_a_room_state_readback(self):
        async def exercise():
            m = await self.manager()
            await m.async_action("resume")
            await m.async_action("eco_boost")
            await m.async_action("top_boost")
            await m.async_action("off")
            self.assertEqual(self.coord.post_action_polls_scheduled, 4)
            await m.async_action("eco_boost")
            with patch.object(module, "utcnow", return_value=self.now + timedelta(minutes=31)):
                await m.async_recover()
            self.assertEqual(self.coord.post_action_polls_scheduled, 6)
        asyncio.run(exercise())

    def test_legacy_boost_is_restart_safe_eco(self):
        async def exercise():
            m = await self.manager()
            result = await m.async_action("boost")
            self.assertEqual(result["mode"], "eco_boost")
            self.assertEqual(self.store.saved["kind"], "resume_and_adapt")

        asyncio.run(exercise())

    def test_failure_on_flow_restore_retries_only_adaptation(self):
        async def exercise():
            m = await self.manager()
            await m.async_action("top_boost")
            self.client.fail_flow_get = True
            with patch.object(module, "utcnow", return_value=self.now + timedelta(minutes=31)):
                await m.async_recover()
            self.assertEqual(self.store.saved["kind"], "adapt_only")
            self.assertEqual(m.status()["mode"], "schedule")
            resumes = sum(x == ("quick_action", "resume") for x in self.client.calls)
            self.assertEqual(resumes, 1)
            self.client.fail_flow_get = False
            with patch.object(module, "utcnow", return_value=self.now + timedelta(minutes=37)):
                await m.async_recover()
            self.assertEqual(m.status()["mode"], "schedule")
            self.assertIsNone(m.status()["kind"])
            self.assertEqual(
                sum(x == ("quick_action", "resume") for x in self.client.calls),
                1,
            )
        asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()
