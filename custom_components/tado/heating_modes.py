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
        self._mode: str = "unknown"  # last requested HA mode; not device readback
        self._cancel_timer = None
        self._closed = False
        self._last_error: str | None = None

    async def async_start(self) -> None:
        """Restore a pending Top Boost or failed adaptation restoration."""
        saved = await self.store.async_load()
        if isinstance(saved, dict):
            self._mode = (
                saved["mode"] if saved.get("mode") in (
                    "schedule", "off", "eco_boost", "top_boost", "unknown"
                ) else "unknown"
            )
            kind, due = saved.get("kind"), _parse_due(saved.get("due"))
            if kind in ("resume_and_adapt", "adapt_only") and due is not None:
                self._pending_kind, self._pending_due = kind, due
                # Older state may not include a mode; recovery still proceeds.
            elif kind is not None:
                _LOGGER.warning("Ignoring invalid tado X recovery state")
        self._arm_timer()
        self._notify()

    def async_stop(self) -> None:
        """Cancel runtime callback, retaining stored recovery for restart."""
        self._closed = True
        self._cancel_scheduled()

    def status(self) -> dict:
        due = self._pending_due
        return {
            "mode": self._mode,
            "mode_label": {
                "unknown": "Unknown",
                "schedule": "Schedules",
                "off": "Heating Off",
                "eco_boost": "Eco Boost",
                "top_boost": "Top Boost",
            }[self._mode],
            "mode_source": "last_action_through_home_assistant_not_tado_readback",
            "mode_confirmed_by_device": False,
            "pending": self._pending_kind is not None,
            "kind": self._pending_kind,
            "due_utc": due.isoformat(timespec="seconds") if due else None,
            "seconds_until_due": max(0, int((due - utcnow()).total_seconds()))
            if due else None,
            "last_recovery_error": self._last_error,
            "storage_persistent": True,
            "eco_boost_restart_safe": True,
            "top_boost_restart_safe": True,
        }

    def _notify(self):
        # Updates the Home Assistant home-mode sensor without forcing extra
        # tado API/cloud requests. Also updates on the normal zone refresh.
        self.coordinator.async_update_listeners()

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
                           due: datetime | None = None,
                           *, mode: str | None = None) -> None:
        """Save before scheduling, ensuring failed storage cannot orphan a boost."""
        if kind is not None and (kind not in ("resume_and_adapt", "adapt_only")
                                 or due is None or due.tzinfo is None):
            raise ValueError("Invalid recovery state")
        new_mode = self._mode if mode is None else mode
        if new_mode not in ("schedule", "off", "eco_boost", "top_boost", "unknown"):
            raise ValueError("Unsupported home heating mode")
        await self.store.async_save(
            {"kind": kind, "due": due.isoformat() if due else None,
             "mode": new_mode}
        )
        self._pending_kind, self._pending_due = kind, due
        self._mode = new_mode
        self._last_error = None
        self._arm_timer()
        self._notify()

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

    def _queue_room_readback(self):
        # The coordinator reads actual room/overlay state 3 seconds after an
        # explicit write or the scheduled recovery. During unit tests or a
        # failed/unloaded coordinator the method may be absent.
        if self._closed:
            return
        schedule = getattr(self.coordinator, "schedule_post_action_room_refresh", None)
        if callable(schedule):
            schedule()

    async def async_action(self, action: str) -> dict:
        try:
            return await self._async_action_impl(action)
        finally:
            # Even if tado times out, it might have applied the command.
            # Readback confirms the room state rather than assuming success.
            self._queue_room_readback()

    async def async_recover(self) -> dict:
        try:
            return await self._async_recover_impl()
        finally:
            self._queue_room_readback()

    async def _async_recover_impl(self) -> dict:
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
                await self._set_pending(
                    None,
                    mode="schedule" if kind == "resume_and_adapt" else None,
                )
                _LOGGER.info("tado X heating boost restoration completed")
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
                    retry_kind, utcnow() + timedelta(minutes=RECOVERY_RETRY_MINUTES),
                    mode="schedule" if retry_kind == "adapt_only"
                    and kind == "resume_and_adapt" else None,
                )
                self._last_error = str(err)
            return self.status()

    async def _async_action_impl(self, action: str) -> dict:
        """Execute user actions with persisted recovery for BOTH boost modes.

        'boost' is a backward-compatible alias of 'eco_boost'.
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
                previous_mode = self._mode
                previous_kind, previous_due = self._pending_kind, self._pending_due
                await self._set_pending(
                    "resume_and_adapt", deadline, mode="top_boost"
                )
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
                    await self._set_pending(
                        recovery_kind, utcnow(),
                        mode="schedule" if boost_attempted else previous_mode,
                    )
                    try:
                        if boost_attempted:
                            await self._resume_and_adapt()
                        else:
                            await self._ensure_adaptation_enabled()
                        await self._set_pending(
                            None if boost_attempted else previous_kind,
                            None if boost_attempted else previous_due,
                            mode="schedule" if boost_attempted else previous_mode,
                        )
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
                            utcnow() + timedelta(minutes=RECOVERY_RETRY_MINUTES),
                            mode="schedule" if retry_kind == "adapt_only"
                            and boost_attempted else previous_mode
                            if not boost_attempted else None,
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
                        utcnow() + timedelta(minutes=RECOVERY_RETRY_MINUTES),
                        mode="schedule",
                    )
                    raise
                await self._set_pending(None, mode="schedule")
                return {
                    **result, "action": "resume",
                    "flow_adaptation_ensured_enabled": True,
                    "flow_adaptation_changed_by_integration": adapted,
                    "cancelled_top_boost": True,
                }

            if action == "off":
                result = await self.client.heating_quick_action("off")
                # An old Top/Eco timer must never resume an explicitly
                # switched-off home. Restore adaptive flow independently.
                await self._set_pending(None, mode="off")
                try:
                    adapted = await self._ensure_adaptation_enabled()
                except Exception:
                    await self._set_pending(
                        "adapt_only",
                        utcnow() + timedelta(minutes=RECOVERY_RETRY_MINUTES),
                    )
                    raise
                return {
                    **result, "action": "off", "mode": "off",
                    "flow_adaptation_ensured_enabled": True,
                    "flow_adaptation_changed_by_integration": adapted,
                    "cancelled_previous_boost": True,
                }

            # Eco Boost preserves the app's normal quick action, but makes
            # 30-minute expiry restart-safe just like Top Boost. Adaptation
            # is enabled first, without changing maximum flow temperature.
            await self._ensure_adaptation_enabled()
            deadline = utcnow() + timedelta(minutes=TOP_BOOST_MINUTES)
            previous_mode = self._mode
            previous_kind, previous_due = self._pending_kind, self._pending_due
            await self._set_pending(
                "resume_and_adapt", deadline, mode="eco_boost"
            )
            attempted = False
            try:
                attempted = True
                result = await self.client.heating_quick_action("boost")
            except Exception:
                # The HTTP request may have reached tado even if the client
                # experienced a failure. Restore immediately if possible.
                try:
                    await self._resume_and_adapt()
                    await self._set_pending(None, mode="schedule")
                except Exception as recovery_error:
                    _LOGGER.warning(
                        "Eco Boost failed and immediate recovery failed: %s",
                        recovery_error,
                    )
                    await self._set_pending(
                        "resume_and_adapt",
                        utcnow() + timedelta(minutes=RECOVERY_RETRY_MINUTES),
                    )
                raise
            return {
                **result,
                "action": "eco_boost", "mode": "eco_boost",
                "flow_adaptation_ensured_enabled": True,
                "boost_duration_minutes": TOP_BOOST_MINUTES,
                "auto_adaptation_restores_at_utc": deadline.isoformat(),
                "scheduled_recovery_persisted": True,
                "return_to_schedule_after_minutes": TOP_BOOST_MINUTES,
                "cancelled_previous_boost": previous_kind is not None,
            }
