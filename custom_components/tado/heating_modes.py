"""Safely coordinate the two whole-home heating boosts.

Eco Boost is the official tado X quick-action boost with adaptation enabled.
Top Boost temporarily disables tado's flow-temperature adaptation, uses the
same 30-minute room boost, and restores schedules + adaptation afterwards.

A persistent UTC deadline means HA restarts cannot silently discard the
scheduled recovery. All commands are initiated by the user or by a pending
recovery from their earlier action; polling never causes a new boost.

This writes only through the existing serialised PyTado/HOPS client.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import logging

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.storage import Store

from .tadox_ext import TadoXClient

_LOGGER = logging.getLogger(__name__)
TOP_BOOST_MINUTES = 30
RECOVERY_RETRY_MINUTES = 5
STORAGE_VERSION = 1


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_due(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        due = datetime.fromisoformat(value)
    except ValueError:
        return None
    return due.astimezone(timezone.utc) if due.tzinfo else None


class AdaptationRestoreError(HomeAssistantError):
    """Schedules resumed, but automatic flow adaptation still needs recovery."""


class HeatingModeManager:
    """Persisted, serialised tado X whole-home heating mode control."""

    def __init__(self, hass, coordinator, *, store=None, schedule=None):
        self.hass = hass
        self.coordinator = coordinator
        self.client = TadoXClient(coordinator)
        self.store = store if store is not None else Store(
            hass, STORAGE_VERSION, f"tado_x_heating_mode_{coordinator.home_id}"
        )
        self._schedule_callback = schedule or async_track_point_in_utc_time
        self._lock = asyncio.Lock()
        self._pending_kind: str | None = None
        self._pending_due: datetime | None = None
        self._cancel_timer = None
        self._closed = False
        self._last_error: str | None = None

    async def async_start(self) -> None:
        """Restore a pending Top Boost or failed adaptation restoration."""
        saved = await self.store.async_load()
        if isinstance(saved, dict):
            kind, due = saved.get("kind"), _parse_due(saved.get("due"))
            if kind in ("resume_and_adapt", "adapt_only") and due is not None:
                self._pending_kind, self._pending_due = kind, due
            elif saved:
                _LOGGER.warning("Ignoring invalid tado X recovery state")
        self._arm_timer()

    def async_stop(self) -> None:
        """Cancel runtime callback, retaining stored recovery for restart."""
        self._closed = True
        self._cancel_scheduled()

    def status(self) -> dict:
        due = self._pending_due
        return {
            "pending": self._pending_kind is not None,
            "kind": self._pending_kind,
            "due_utc": due.isoformat(timespec="seconds") if due else None,
            "seconds_until_due": max(0, int((due - utcnow()).total_seconds()))
            if due else None,
            "last_recovery_error": self._last_error,
            "storage_persistent": True,
        }

    def _cancel_scheduled(self):
        if self._cancel_timer is not None:
            self._cancel_timer()
            self._cancel_timer = None

    def _arm_timer(self) -> None:
        self._cancel_scheduled()
        if self._closed or self._pending_due is None:
            return
        due = max(self._pending_due, utcnow() + timedelta(seconds=1))

        def on_deadline(now) -> None:
            if not self._closed:
                self.hass.async_create_task(self.async_recover())

        self._cancel_timer = self._schedule_callback(self.hass, on_deadline, due)

    async def _set_pending(self, kind: str | None,
                           due: datetime | None = None) -> None:
        """Save before scheduling, ensuring failed storage cannot orphan a boost."""
        if kind is not None and (kind not in ("resume_and_adapt", "adapt_only")
                                 or due is None or due.tzinfo is None):
            raise ValueError("Invalid recovery state")
        await self.store.async_save(
            {"kind": kind, "due": due.isoformat() if due else None}
        )
        self._pending_kind, self._pending_due = kind, due
        self._last_error = None
        self._arm_timer()

    async def _ensure_adaptation_enabled(self):
        """Idempotent: only PATCH when tado reports it was disabled."""
        flow = await self.client.get_flow()
        if not isinstance(flow, dict):
            raise HomeAssistantError(
                "Cannot verify automatic flow adaptation; recovery remains pending"
            )
        adaptation = flow.get("autoAdaptation")
        state = adaptation.get("enabled") if isinstance(adaptation, dict) else None
        if state is True:
            return False
        if state is not False:
            raise HomeAssistantError(
                "Automatic flow adaptation state unavailable; recovery remains pending"
            )
        await self.client.set_flow(enabled=True)
        if self.coordinator.x_settings:
            await self.coordinator.x_settings.async_request_refresh()
        return True

    async def _resume_and_adapt(self) -> tuple[dict, bool]:
        """Restore schedules first and always reenable automatic adaptation.

        If schedule resumption fails, still attempt adaptation, but report
        failure so that a pending recovery is retried.
        """
        response = None
        resume_error = None
        try:
            response = await self.client.heating_quick_action("resume")
        except Exception as err:
            resume_error = err
        adapt_error = None
        adapted = False
        try:
            adapted = await self._ensure_adaptation_enabled()
        except Exception as err:
            adapt_error = err
        if resume_error:
            raise HomeAssistantError(
                "Resume schedules failed; automatic flow adaptation "
                + ("also failed" if adapt_error else "checked")
            ) from resume_error
        if adapt_error:
            raise AdaptationRestoreError(
                "Schedules resumed but automatic flow adaptation could not "
                "be restored; will retry"
            ) from adapt_error
        return response, adapted

    async def async_recover(self) -> dict:
        """Recover a previously requested Top Boost, retrying safely."""
        async with self._lock:
            if self._closed or self._pending_kind is None:
                return self.status()
            if self._pending_due and self._pending_due > utcnow():
                self._arm_timer()
                return self.status()
            kind = self._pending_kind
            try:
                if kind == "resume_and_adapt":
                    # If resume succeeds but adaptation fails, remember only
                    # adapt_only so retries never repeatedly cancel later
                    # room overrides unnecessarily.
                    await self._resume_and_adapt()
                else:
                    await self._ensure_adaptation_enabled()
                await self._set_pending(None)
                _LOGGER.info("tado X Top Boost restoration completed")
            except Exception as err:
                # Resume already succeeded: retry ONLY enabling adaptation,
                # never reset any room changes made in the meantime.
                retry_kind = (
                    "adapt_only" if isinstance(err, AdaptationRestoreError)
                    else kind
                )
                _LOGGER.warning(
                    "tado X heating recovery incomplete; retry in %d minutes: %s",
                    RECOVERY_RETRY_MINUTES, err,
                )
                await self._set_pending(
                    retry_kind, utcnow() + timedelta(minutes=RECOVERY_RETRY_MINUTES)
                )
                self._last_error = str(err)
            return self.status()

    async def async_action(self, action: str) -> dict:
        """Execute a user action and manage any outstanding Top Boost timer.

        Former 'boost' remains an alias of 'eco_boost' for HA automation
        compatibility. New actions cannot run concurrently.
        """
        if action not in ("off", "resume", "boost", "eco_boost", "top_boost"):
            raise HomeAssistantError("Unknown tado X heating quick action")
        async with self._lock:
            if self._closed:
                raise HomeAssistantError("tado X heating manager is stopped")
            if action == "top_boost":
                # Persist the deadline BEFORE disabling adaptation, so a
                # crash or restart cannot leave the system disabled forever.
                deadline = utcnow() + timedelta(minutes=TOP_BOOST_MINUTES)
                await self._set_pending("resume_and_adapt", deadline)
                boost_attempted = False
                try:
                    await self.client.set_flow(enabled=False)
                    if self.coordinator.x_settings:
                        await self.coordinator.x_settings.async_request_refresh()
                    boost_attempted = True
                    result = await self.client.heating_quick_action("boost")
                except Exception:
                    # If the boost was never sent, do NOT resume schedules:
                    # manually configured rooms must remain untouched.
                    # If it may have been sent, resume to undo an unknown
                    # partial boost and restore adaptation immediately.
                    recovery_kind = (
                        "resume_and_adapt" if boost_attempted else "adapt_only"
                    )
                    await self._set_pending(recovery_kind, utcnow())
                    try:
                        if boost_attempted:
                            await self._resume_and_adapt()
                        else:
                            await self._ensure_adaptation_enabled()
                        await self._set_pending(None)
                    except Exception as recovery_error:
                        _LOGGER.warning(
                            "Top Boost failed and immediate recovery failed: %s",
                            recovery_error,
                        )
                        retry_kind = (
                            "adapt_only"
                            if isinstance(recovery_error, AdaptationRestoreError)
                            else recovery_kind
                        )
                        await self._set_pending(
                            retry_kind,
                            utcnow() + timedelta(minutes=RECOVERY_RETRY_MINUTES)
                        )
                    raise
                return {
                    **result, "action": "top_boost", "mode": "top_boost",
                    "auto_adaptation_disabled_temporarily": True,
                    "auto_adaptation_restores_at_utc": deadline.isoformat(),
                    "scheduled_recovery_persisted": True,
                    "return_to_schedule_after_minutes": TOP_BOOST_MINUTES,
                }

            if action == "resume":
                # Separate resume failure from adaptation failure to avoid
                # using an automatic resume retry after schedules succeeded.
                # Any outstanding Top Boost is superseded by this command.
                try:
                    result = await self.client.heating_quick_action("resume")
                except Exception:
                    # Still restore adaptation even if resume API fails.
                    try:
                        await self._ensure_adaptation_enabled()
                    except Exception:
                        pass
                    raise
                try:
                    adapted = await self._ensure_adaptation_enabled()
                except Exception:
                    await self._set_pending(
                        "adapt_only",
                        utcnow() + timedelta(minutes=RECOVERY_RETRY_MINUTES)
                    )
                    raise
                await self._set_pending(None)
                return {
                    **result, "action": "resume",
                    "flow_adaptation_ensured_enabled": True,
                    "flow_adaptation_changed_by_integration": adapted,
                    "cancelled_top_boost": True,
                }

            if action == "off":
                result = await self.client.heating_quick_action("off")
            else:
                # 'boost' from older automations means Eco Boost.
                result = await self.client.heating_quick_action("boost")

            # Off or Eco Boost supersedes a pending Top Boost. Never let the
            # old timer later resume all schedules and undo the newer choice.
            # Ensure adaptive flow control is on when switching out of Top.
            try:
                adapted = await self._ensure_adaptation_enabled()
            except Exception:
                await self._set_pending(
                    "adapt_only",
                    utcnow() + timedelta(minutes=RECOVERY_RETRY_MINUTES)
                )
                raise
            await self._set_pending(None)
            return {
                **result,
                "action": "off" if action == "off" else "eco_boost",
                "mode": "off" if action == "off" else "eco_boost",
                "flow_adaptation_ensured_enabled": True,
                "flow_adaptation_changed_by_integration": adapted,
                "boost_duration_minutes": TOP_BOOST_MINUTES
                if action != "off" else None,
                "cancelled_top_boost": True,
            }
