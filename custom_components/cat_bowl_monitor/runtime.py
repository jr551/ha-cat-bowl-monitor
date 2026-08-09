"""Runtime for Cat Bowl Monitor."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from collections.abc import Callable
from contextlib import suppress
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.components.camera import async_get_image
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .ai import (
    ProviderError,
    async_assess_bowl,
    async_compare_consumption,
    provider_settings_from_config,
)
from .camera_source import private_esphome_snapshot_url
from .const import (
    CAPTURE_TIMEOUT,
    CONF_AFTERNOON_TIME,
    CONF_BOWL_DESCRIPTION,
    CONF_CAMERA_ENTITY,
    CONF_CHECK_INTERVAL_HOURS,
    CONF_CONFIDENCE_THRESHOLD,
    CONF_CONFIRMATION_SAMPLES,
    CONF_FEEDING_SENSOR,
    CONF_LEFT_FEED_ENTITY,
    CONF_LIGHT_ENTITY,
    CONF_MORNING_TIME,
    CONF_NOTIFICATION_SERVICE,
    CONF_NOTIFICATIONS,
    CONF_NOTIFY_NO_ACTION,
    CONF_PET_NAME,
    CONF_RIGHT_FEED_ENTITY,
    CONFIRMATION_DELAY_SECONDS,
    DEFAULT_AFTERNOON_TIME,
    DEFAULT_BOWL_DESCRIPTION,
    DEFAULT_CHECK_INTERVAL_HOURS,
    DEFAULT_CONFIDENCE_THRESHOLD,
    DEFAULT_CONFIRMATION_SAMPLES,
    DEFAULT_MORNING_TIME,
    DEFAULT_NOTIFICATIONS,
    DEFAULT_NOTIFY_NO_ACTION,
    DEFAULT_PET_NAME,
    DOMAIN,
    EVENT_BASELINE_RESET,
    EVENT_BECAME_EMPTY,
    EVENT_CHECKED,
    EVENT_FEED_REQUESTED,
    EVENT_RECOVERED,
    EVENT_SCHEDULED_CYCLE,
    ILLUMINATION_SETTLE_SECONDS,
    MAX_CAMERA_IMAGE_BYTES,
    MAX_CONSECUTIVE_FAILURES_BEFORE_UNAVAILABLE,
    POST_FEED_BASELINE_RETRY_SECONDS,
    POST_FEED_SETTLE_SECONDS,
    SCHEDULE_CATCHUP_MINUTES,
    STORE_VERSION,
)
from .image import camera_image_is_usable
from .logic import (
    Assessment,
    BowlReading,
    Consumption,
    apply_confirmation,
    interval_schedule,
    is_feeding_completion,
    is_usable_primary_assessment,
    should_notify_cycle,
)

_LOGGER = logging.getLogger(__name__)


class CameraImageNotUsable(RuntimeError):
    """The current frame cannot safely support a feeding decision."""


def _new_bowl_state() -> dict[str, Any]:
    return {
        "stable_level": "unknown",
        "candidate_level": None,
        "candidate_count": 0,
        "raw_level": "unknown",
        "fill_percent": None,
        "confidence": None,
        "visible": False,
    }


class BowlRuntime:
    """Run guarded two-bowl checks and optional conditional feeding."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.camera_entity = str(entry.data[CONF_CAMERA_ENTITY])
        self.bowls = {"dry": _new_bowl_state(), "wet": _new_bowl_state()}
        self._listeners: set[Callable[[], None]] = set()
        self._remove_schedule: list[Callable[[], None]] = []
        self._check_lock = asyncio.Lock()
        self._cycle_lock = asyncio.Lock()
        self._feed_baseline_task: asyncio.Task[None] | None = None
        self._internal_feed_requests = 0
        self._store = Store(hass, STORE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self.latest_images: dict[str, bytes | None] = {
            "latest": None,
            "before": None,
            "after": None,
        }
        self.image_updated: dict[str, datetime | None] = {
            "latest": None,
            "before": None,
            "after": None,
        }
        self.summary = ""
        self.last_checked_at: datetime | None = None
        self.last_success_at: datetime | None = None
        self.last_error = ""
        self.last_model = ""
        self.check_count = 0
        self.consecutive_failures = 0
        self.last_cycle_key = ""
        self.last_cycle_at: datetime | None = None
        self.last_cycle_status = "never_run"
        self.last_cycle_message = ""
        self.last_feed_result = "not_requested"
        self.last_family_delivery = ""
        self.baseline_at: datetime | None = None
        self.baseline_reason = ""
        self.last_feeder_completion_at: datetime | None = None
        self.pending_feed_baseline_at: datetime | None = None
        self.consumption_from_at: datetime | None = None
        self.consumption_to_at: datetime | None = None
        self.consumption: Consumption | None = None
        self.consumption_baseline_reason = ""
        self._user_key = (
            "cat-bowl-" + hashlib.sha256(entry.entry_id.encode()).hexdigest()[:16]
        )
        self._image_directory = Path(hass.config.path(DOMAIN, entry.entry_id))

    @property
    def options(self) -> dict[str, Any]:
        return {**self.entry.data, **self.entry.options}

    @property
    def required_samples(self) -> int:
        return int(
            self.options.get(CONF_CONFIRMATION_SAMPLES, DEFAULT_CONFIRMATION_SAMPLES)
        )

    @property
    def confidence_threshold(self) -> float:
        return float(
            self.options.get(CONF_CONFIDENCE_THRESHOLD, DEFAULT_CONFIDENCE_THRESHOLD)
        )

    @property
    def notifications_enabled(self) -> bool:
        return bool(self.options.get(CONF_NOTIFICATIONS, DEFAULT_NOTIFICATIONS))

    @property
    def notify_no_action(self) -> bool:
        return bool(self.options.get(CONF_NOTIFY_NO_ACTION, DEFAULT_NOTIFY_NO_ACTION))

    @property
    def right_feed_entity(self) -> str:
        return str(self.options.get(CONF_RIGHT_FEED_ENTITY, "")).strip()

    @property
    def light_entity(self) -> str:
        return str(self.options.get(CONF_LIGHT_ENTITY, "")).strip()

    @property
    def left_feed_entity(self) -> str:
        return str(self.options.get(CONF_LEFT_FEED_ENTITY, "")).strip()

    @property
    def feeding_sensor(self) -> str:
        return str(self.options.get(CONF_FEEDING_SENSOR, "")).strip()

    @property
    def notification_service(self) -> str:
        return str(self.options.get(CONF_NOTIFICATION_SERVICE, "")).strip()

    @property
    def pet_name(self) -> str:
        value = " ".join(str(self.options.get(CONF_PET_NAME, DEFAULT_PET_NAME)).split())
        return value[:60] or DEFAULT_PET_NAME

    @property
    def bowl_description(self) -> str:
        return str(self.options.get(CONF_BOWL_DESCRIPTION, DEFAULT_BOWL_DESCRIPTION))

    @property
    def schedule_times(self) -> tuple[time, ...]:
        interval = int(
            self.options.get(CONF_CHECK_INTERVAL_HOURS, DEFAULT_CHECK_INTERVAL_HOURS)
        )
        if interval:
            anchor = _parse_time(
                self.options.get(CONF_MORNING_TIME, DEFAULT_MORNING_TIME)
            )
            return interval_schedule(anchor, interval)
        values = (
            self.options.get(CONF_MORNING_TIME, DEFAULT_MORNING_TIME),
            self.options.get(CONF_AFTERNOON_TIME, DEFAULT_AFTERNOON_TIME),
        )
        return tuple(sorted({_parse_time(value) for value in values}))

    @property
    def available(self) -> bool:
        return bool(
            self.last_success_at is not None
            and self.consecutive_failures < MAX_CONSECUTIVE_FAILURES_BEFORE_UNAVAILABLE
        )

    def bowl(self, name: str) -> dict[str, Any]:
        return self.bowls[name]

    async def async_start(self) -> None:
        """Restore state, register schedules, and take one safe sample."""
        await self._async_restore()
        self._remove_schedule.append(
            async_track_state_change_event(
                self.hass, [self.camera_entity], self._camera_state_changed
            )
        )
        if self.feeding_sensor:
            self._remove_schedule.append(
                async_track_state_change_event(
                    self.hass, [self.feeding_sensor], self._feeding_sensor_changed
                )
            )
            if self.pending_feed_baseline_at is not None:
                self._schedule_feed_baseline(self.pending_feed_baseline_at)
        for scheduled_time in self.schedule_times:
            self._remove_schedule.append(
                async_track_time_change(
                    self.hass,
                    self.async_scheduled_cycle,
                    hour=scheduled_time.hour,
                    minute=scheduled_time.minute,
                    second=0,
                )
            )
        now = dt_util.now()
        catchup_at = next(
            (
                scheduled
                for scheduled in self._scheduled_datetimes(now)
                if scheduled
                <= now
                < scheduled + timedelta(minutes=SCHEDULE_CATCHUP_MINUTES)
                and self.last_cycle_key != self._cycle_key(scheduled)
            ),
            None,
        )
        if catchup_at is not None:
            self.hass.async_create_background_task(
                self._async_when_camera_ready(self.async_scheduled_cycle, catchup_at),
                name=f"{DOMAIN}_{self.entry.entry_id}_catchup",
                eager_start=True,
            )
        else:
            self.hass.async_create_background_task(
                self._async_when_camera_ready(self.async_check),
                name=f"{DOMAIN}_{self.entry.entry_id}_initial_check",
                eager_start=True,
            )

    async def async_stop(self) -> None:
        for remove in self._remove_schedule:
            remove()
        self._remove_schedule.clear()
        if self._feed_baseline_task is not None:
            self._feed_baseline_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await self._feed_baseline_task
            self._feed_baseline_task = None

    @callback
    def _camera_state_changed(self, _event: Event) -> None:
        """Refresh recovery controls when the camera becomes available."""
        self._notify()

    @callback
    def _feeding_sensor_changed(self, event: Event) -> None:
        """Reset the comparison whenever the feeder completes a dispense."""
        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")
        if not is_feeding_completion(
            old_state.state if old_state is not None else None,
            new_state.state if new_state is not None else None,
        ):
            return
        completed_at = dt_util.utcnow()
        self.last_feeder_completion_at = completed_at
        if self._internal_feed_requests:
            return
        self._schedule_feed_baseline(completed_at)

    @callback
    def _schedule_feed_baseline(self, completed_at: datetime) -> None:
        if self._feed_baseline_task is not None:
            self._feed_baseline_task.cancel()
        self._feed_baseline_task = self.hass.async_create_background_task(
            self._async_reset_baseline_after_feed(completed_at),
            name=f"{DOMAIN}_{self.entry.entry_id}_post_feed_baseline",
            eager_start=True,
        )

    async def _async_reset_baseline_after_feed(self, completed_at: datetime) -> None:
        """Invalidate polluted consumption and capture a post-feed reference."""
        self.pending_feed_baseline_at = completed_at
        self.baseline_reason = "feeder_completion_pending"
        self.baseline_at = None
        self.consumption = None
        self.consumption_from_at = None
        self.consumption_to_at = None
        self.consumption_baseline_reason = ""
        self.latest_images["baseline"] = None
        self.image_updated["baseline"] = None
        await self.hass.async_add_executor_job(self._remove_image, "baseline")
        await self._async_save()
        self._notify()
        self.hass.bus.async_fire(
            EVENT_BASELINE_RESET,
            self._baseline_payload("pending"),
        )

        elapsed = max(0.0, (dt_util.utcnow() - completed_at).total_seconds())
        delays = (
            max(0.0, POST_FEED_SETTLE_SECONDS - elapsed),
            *POST_FEED_BASELINE_RETRY_SECONDS,
        )
        for attempt, delay in enumerate(delays, start=1):
            await asyncio.sleep(delay)
            if self.pending_feed_baseline_at != completed_at:
                return
            if self._cycle_lock.locked() or self._check_lock.locked():
                continue
            async with self._check_lock:
                if self._cycle_lock.locked():
                    continue
                try:
                    jpeg, assessment = await self._async_capture_assess("latest")
                    await self._async_apply_assessment(assessment)
                except Exception as err:  # noqa: BLE001 - recovery must stay pending
                    self.baseline_reason = "feeder_completion_capture_retrying"
                    await self._async_record_failure(err)
                    self.hass.bus.async_fire(
                        EVENT_BASELINE_RESET,
                        self._baseline_payload("retrying"),
                    )
                    continue
                await self._async_set_baseline(jpeg, "feeder_completion")
                await self._async_save()
                self._notify()
                self.hass.bus.async_fire(
                    EVENT_BASELINE_RESET,
                    self._baseline_payload("completed"),
                )
                return

        self.baseline_reason = "feeder_completion_capture_failed"
        await self._async_save()
        self._notify()
        self.hass.bus.async_fire(
            EVENT_BASELINE_RESET,
            self._baseline_payload("failed"),
        )

    def _scheduled_datetimes(self, moment: datetime) -> tuple[datetime, ...]:
        return tuple(
            moment.replace(
                hour=scheduled_time.hour,
                minute=scheduled_time.minute,
                second=0,
                microsecond=0,
            )
            for scheduled_time in self.schedule_times
        )

    def add_listener(self, callback_func: Callable[[], None]) -> Callable[[], None]:
        self._listeners.add(callback_func)

        def remove() -> None:
            self._listeners.discard(callback_func)

        return remove

    def _notify(self) -> None:
        for callback_func in tuple(self._listeners):
            callback_func()

    async def _async_when_camera_ready(
        self,
        action: Callable[..., Any],
        *args: Any,
    ) -> None:
        """Wait briefly for camera platforms during startup or entry reload."""
        for _ in range(12):
            state = self.hass.states.get(self.camera_entity)
            if state is not None and state.state not in {
                STATE_UNKNOWN,
                STATE_UNAVAILABLE,
            }:
                await action(*args)
                return
            await asyncio.sleep(5)
        await self._async_record_failure("Camera was not ready within 60 seconds")

    async def async_check(self, _now: datetime | None = None) -> None:
        """Take one manual/status sample. This path can never dispense."""
        if self._check_lock.locked() or self._cycle_lock.locked():
            return
        async with self._check_lock:
            try:
                _, assessment = await self._async_capture_assess("latest")
            except Exception as err:  # noqa: BLE001 - manual checks never actuate
                await self._async_record_failure(err)
                return
            await self._async_apply_assessment(assessment)
            await self._async_save()
            self._notify()

    async def async_scheduled_cycle(self, now: datetime | None = None) -> None:
        """Run one idempotent assess-feed-reassess cycle."""
        if self._cycle_lock.locked():
            return
        moment = now or dt_util.now()
        key = self._cycle_key(moment)
        if self.last_cycle_key == key:
            return
        async with self._cycle_lock:
            # Persist the cycle key before any actuator call. A restart can miss
            # a feed, but can never repeat one.
            self.last_cycle_key = key
            self.last_cycle_at = dt_util.utcnow()
            self.last_cycle_status = "checking"
            self.last_feed_result = "not_requested"
            await self._async_save()
            self._notify()
            try:
                _, first = await self._async_capture_assess("before")
                await self._async_apply_assessment(first)
                await asyncio.sleep(CONFIRMATION_DELAY_SECONDS)
                before_jpeg, second = await self._async_capture_assess("before")
                await self._async_apply_assessment(second)

                usable = all(
                    is_usable_primary_assessment(
                        assessment.dry, self.confidence_threshold
                    )
                    for assessment in (first, second)
                )
                if not usable:
                    self.last_cycle_status = "inconclusive"
                    self.last_feed_result = "right=not_requested; left=not_requested"
                    self.last_cycle_message = (
                        f"{self.pet_name} food check could not see the dry bowl."
                    )
                    self.last_family_delivery = "suppressed_inconclusive"
                    self.consecutive_failures += 1
                    self.last_error = "Primary dry-food zone was not clearly visible"
                    self.hass.bus.async_fire(EVENT_SCHEDULED_CYCLE, self._cycle_payload())
                    return

                await self._async_compare_with_baseline(before_jpeg)

                dry_empty = self._confirmed_empty(first.dry, second.dry)
                wet_empty = self._confirmed_empty(first.wet, second.wet)
                right_needed = dry_empty
                left_needed = dry_empty and wet_empty

                right_result = "not_needed"
                left_result = "not_needed"
                right_error = (
                    self._feed_action_error(self.right_feed_entity)
                    if right_needed
                    else None
                )
                left_error = (
                    self._feed_action_error(self.left_feed_entity)
                    if left_needed
                    else None
                )
                if self.feeding_sensor and self.hass.states.is_state(
                    self.feeding_sensor, "on"
                ):
                    if right_needed:
                        right_error = "feeder_busy"
                    if left_needed:
                        left_error = "feeder_busy"

                # Resolve every required action before calling either one. This
                # prevents a partial feed when both bowls are empty but one
                # scene is missing or invalid.
                if right_error or left_error:
                    if right_needed:
                        right_result = right_error or "blocked_by_other_action"
                    if left_needed:
                        left_result = left_error or "blocked_by_other_action"
                else:
                    if right_needed:
                        right_result = await self._async_request_feed(
                            "right", self.right_feed_entity, "configured scene"
                        )
                    if left_needed:
                        left_result = await self._async_request_feed(
                            "left", self.left_feed_entity, "configured scene"
                        )
                any_requested = right_result.startswith(
                    "sent"
                ) or left_result.startswith("sent")
                after_jpeg: bytes | None
                if any_requested:
                    await asyncio.sleep(POST_FEED_SETTLE_SECONDS)
                    try:
                        after_jpeg, after = await self._async_capture_assess("after")
                        await self._async_apply_assessment(after)
                    except Exception as err:  # noqa: BLE001 - feed already happened
                        after_jpeg = None
                        after = second
                        await self._async_record_failure(err)
                        self._schedule_feed_baseline(dt_util.utcnow())
                else:
                    after_jpeg = before_jpeg
                    after = second
                    self.latest_images["after"] = before_jpeg
                    self.image_updated["after"] = dt_util.utcnow()
                    await self.hass.async_add_executor_job(
                        self._write_image, "after", before_jpeg
                    )

                if after_jpeg is not None:
                    baseline_reason = (
                        "scheduled_cycle_after_feed"
                        if any_requested
                        else "scheduled_cycle"
                    )
                    await self._async_set_baseline(after_jpeg, baseline_reason)
                self.last_feed_result = f"right={right_result}; left={left_result}"
                feed_failed = (right_needed and right_result == "action_failed") or (
                    left_needed and left_result == "action_failed"
                )
                feed_blocked = (
                    right_needed and not right_result.startswith("sent")
                ) or (left_needed and not left_result.startswith("sent"))
                feed_unverified = (
                    right_needed and right_result != "sent_and_completed"
                ) or (left_needed and left_result != "sent_and_completed")
                if feed_failed or feed_blocked:
                    self.last_cycle_status = "blocked"
                elif feed_unverified:
                    self.last_cycle_status = "unverified"
                else:
                    self.last_cycle_status = "completed"
                self.last_cycle_message = self._build_family_message(
                    right_needed,
                    left_needed,
                    right_result,
                    left_result,
                    second,
                    after,
                )
                if should_notify_cycle(
                    notifications_enabled=self.notifications_enabled,
                    notify_no_action=self.notify_no_action,
                    right_needed=right_needed,
                    left_needed=left_needed,
                ):
                    await self._async_notify_family(self.last_cycle_message)
                else:
                    self.last_family_delivery = "suppressed_no_action"
                payload = self._cycle_payload()
                self.hass.bus.async_fire(EVENT_SCHEDULED_CYCLE, payload)
                if self.last_cycle_status in {"blocked", "unverified"}:
                    persistent_notification.async_create(
                        self.hass,
                        self.last_cycle_message,
                        title=(
                            "Cat Bowl Auto Feed is blocked"
                            if self.last_cycle_status == "blocked"
                            else "Cat Bowl Auto Feed needs verification"
                        ),
                        notification_id=f"{DOMAIN}_{self.entry.entry_id}_blocked",
                    )
            except CameraImageNotUsable as err:
                self.last_cycle_status = "inconclusive"
                self.last_feed_result = "right=not_requested; left=not_requested"
                self.last_cycle_message = (
                    f"{self.pet_name} food check could not see the dry bowl."
                )
                self.last_family_delivery = "suppressed_inconclusive"
                await self._async_record_failure(err)
            except Exception as err:  # noqa: BLE001 - fail closed before feeding
                self.last_cycle_status = "error"
                await self._async_record_failure(err)
                self.last_cycle_message = (
                    f"⚠️ {self.pet_name} food check failed. No food was "
                    "automatically retried. Please check Home Assistant."
                )
                await self._async_notify_family(self.last_cycle_message)
            finally:
                await self._async_save()
                self._notify()

    async def _async_capture_assess(self, image_slot: str) -> tuple[bytes, Assessment]:
        light_state = (
            self.hass.states.get(self.light_entity) if self.light_entity else None
        )
        should_illuminate = bool(
            self.light_entity and light_state is not None and light_state.state != "on"
        )
        turned_on = False
        try:
            if should_illuminate:
                await self.hass.services.async_call(
                    "light",
                    "turn_on",
                    {"entity_id": self.light_entity},
                    blocking=True,
                )
                turned_on = True
                await asyncio.sleep(ILLUMINATION_SETTLE_SECONDS)
            jpeg = await self._async_capture_fresh_image()
        finally:
            if turned_on:
                await self.hass.services.async_call(
                    "light",
                    "turn_off",
                    {"entity_id": self.light_entity},
                    blocking=True,
                )
        if not camera_image_is_usable(jpeg):
            raise CameraImageNotUsable(
                "Camera image was too dark or flat for a safe food check"
            )
        settings = provider_settings_from_config(self.hass, self.options)
        assessment, model = await async_assess_bowl(
            self.hass,
            jpeg,
            self._user_key,
            settings,
            self.bowl_description,
        )
        captured_at = dt_util.utcnow()
        self.latest_images["latest"] = jpeg
        self.image_updated["latest"] = captured_at
        self.latest_images[image_slot] = jpeg
        self.image_updated[image_slot] = captured_at
        await self.hass.async_add_executor_job(self._write_image, image_slot, jpeg)
        if image_slot != "latest":
            await self.hass.async_add_executor_job(self._write_image, "latest", jpeg)
        self.last_model = model
        self.last_checked_at = captured_at
        self.last_success_at = captured_at
        self.last_error = ""
        self.consecutive_failures = 0
        self.check_count += 1
        return jpeg, assessment

    async def _async_capture_fresh_image(self) -> bytes:
        """Prefer a fresh ESPHome web snapshot over HA's cached camera frame."""
        snapshot_url = self._esphome_snapshot_url()
        if snapshot_url:
            try:
                async with asyncio.timeout(CAPTURE_TIMEOUT):
                    async with async_get_clientsession(self.hass).get(
                        snapshot_url, allow_redirects=False
                    ) as response:
                        if response.status == 200:
                            jpeg = await response.content.read(
                                MAX_CAMERA_IMAGE_BYTES + 1
                            )
                            if 0 < len(jpeg) <= MAX_CAMERA_IMAGE_BYTES:
                                return jpeg
            except Exception as err:  # noqa: BLE001 - HA camera is the fallback
                _LOGGER.debug("Direct ESPHome snapshot failed: %s", err)

        image = await async_get_image(
            self.hass, self.camera_entity, timeout=CAPTURE_TIMEOUT
        )
        if not image.content:
            raise RuntimeError("The camera returned an empty image")
        return image.content

    def _esphome_snapshot_url(self) -> str | None:
        """Resolve a trusted local ESPHome camera entry to its snapshot URL."""
        entity = er.async_get(self.hass).async_get(self.camera_entity)
        if entity is None or entity.config_entry_id is None:
            return None
        entry = self.hass.config_entries.async_get_entry(entity.config_entry_id)
        if entry is None or entry.domain != "esphome":
            return None
        return private_esphome_snapshot_url(str(entry.data.get("host", "")))

    async def _async_apply_assessment(self, assessment: Assessment) -> None:
        self.summary = assessment.summary
        for name, reading in (("dry", assessment.dry), ("wet", assessment.wet)):
            bowl = self.bowls[name]
            previous = bowl["stable_level"]
            confirmation = apply_confirmation(
                stable_level=previous,
                candidate_level=bowl["candidate_level"],
                candidate_count=bowl["candidate_count"],
                assessment=reading,
                confidence_threshold=self.confidence_threshold,
                required_samples=self.required_samples,
            )
            bowl.update(
                {
                    "stable_level": confirmation.stable_level,
                    "candidate_level": confirmation.candidate_level,
                    "candidate_count": confirmation.candidate_count,
                    "raw_level": reading.level,
                    "fill_percent": reading.fill_percent,
                    "confidence": reading.confidence,
                    "visible": reading.visible,
                }
            )
            if confirmation.changed:
                payload = self._event_payload(name)
                if confirmation.stable_level == "empty":
                    self.hass.bus.async_fire(EVENT_BECAME_EMPTY, payload)
                elif previous == "empty":
                    self.hass.bus.async_fire(EVENT_RECOVERED, payload)
        self.hass.bus.async_fire(EVENT_CHECKED, self._event_payload())

    async def _async_compare_with_baseline(self, current_jpeg: bytes) -> None:
        baseline = self.latest_images.get("baseline")
        if not baseline or not camera_image_is_usable(baseline):
            self.consumption = None
            self.consumption_from_at = None
            self.consumption_to_at = None
            self.consumption_baseline_reason = ""
            return
        try:
            self.consumption, self.last_model = await async_compare_consumption(
                self.hass,
                baseline,
                current_jpeg,
                self._user_key,
                provider_settings_from_config(self.hass, self.options),
                self.bowl_description,
            )
            self.consumption_from_at = self.baseline_at
            self.consumption_to_at = dt_util.utcnow()
            self.consumption_baseline_reason = self.baseline_reason
        except ProviderError as err:
            _LOGGER.warning("Cat bowl consumption comparison failed: %s", err)
            self.consumption = None
            self.consumption_baseline_reason = ""

    async def _async_set_baseline(self, jpeg: bytes, reason: str) -> None:
        """Persist a bounded reference image for the next comparison."""
        self.latest_images["baseline"] = jpeg
        self.image_updated["baseline"] = dt_util.utcnow()
        self.baseline_at = self.image_updated["baseline"]
        self.baseline_reason = reason
        self.pending_feed_baseline_at = None
        await self.hass.async_add_executor_job(self._write_image, "baseline", jpeg)

    def _confirmed_empty(self, first: BowlReading, second: BowlReading) -> bool:
        return all(
            reading.visible
            and reading.level == "empty"
            and reading.confidence >= self.confidence_threshold
            for reading in (first, second)
        )

    def _feed_action_error(self, entity_id: str) -> str | None:
        if not entity_id or self.hass.states.get(entity_id) is None:
            return "not_configured"
        if entity_id.split(".", 1)[0] not in {"scene", "script", "button"}:
            return "unsupported_entity"
        return None

    async def _async_request_feed(self, side: str, entity_id: str, amount: str) -> str:
        action_error = self._feed_action_error(entity_id)
        if action_error:
            return action_error
        domain = entity_id.split(".", 1)[0]
        service = {
            "scene": "turn_on",
            "script": "turn_on",
            "button": "press",
        }.get(domain)
        if service is None:
            return "unsupported_entity"

        observed_feeding = asyncio.Event()
        observed_done = asyncio.Event()
        saw_feeding = False

        @callback
        def feeding_changed(event: Event) -> None:
            nonlocal saw_feeding
            new_state = event.data.get("new_state")
            if new_state is None:
                return
            if new_state.state == "on":
                saw_feeding = True
                observed_feeding.set()
            elif saw_feeding and new_state.state == "off":
                observed_done.set()

        remove = (
            async_track_state_change_event(
                self.hass, [self.feeding_sensor], feeding_changed
            )
            if self.feeding_sensor
            else None
        )
        self._internal_feed_requests += 1
        try:
            # Fire an event before the call; the event plus persisted cycle key
            # provide an audit trail while retries remain forbidden.
            self.hass.bus.async_fire(
                EVENT_FEED_REQUESTED,
                {
                    "side": side,
                    "amount": amount,
                    "action_entity": entity_id,
                    "cycle_key": self.last_cycle_key,
                },
            )
            await self.hass.services.async_call(
                domain,
                service,
                {"entity_id": entity_id},
                blocking=True,
            )
            if not self.feeding_sensor:
                return "sent_unverified"
            try:
                await asyncio.wait_for(observed_feeding.wait(), timeout=20)
            except TimeoutError:
                return "sent_unverified"
            try:
                await asyncio.wait_for(observed_done.wait(), timeout=60)
            except TimeoutError:
                return "sent_feeding_observed"
            return "sent_and_completed"
        except HomeAssistantError as err:
            _LOGGER.warning("Cat feeder %s action failed: %s", side, err)
            return "action_failed"
        finally:
            self._internal_feed_requests = max(0, self._internal_feed_requests - 1)
            if remove is not None:
                remove()

    async def _async_notify_family(self, message: str) -> None:
        if not self.notifications_enabled:
            self.last_family_delivery = "disabled"
            return
        service_parts = self.notification_service.split(".", 1)
        if len(service_parts) != 2 or not self.hass.services.has_service(
            service_parts[0], service_parts[1]
        ):
            self.last_family_delivery = "service_unavailable"
            return
        try:
            await self.hass.services.async_call(
                service_parts[0],
                service_parts[1],
                {"message": message[:1500]},
                blocking=True,
            )
        except HomeAssistantError as err:
            self.last_family_delivery = "failed"
            _LOGGER.warning("Cat bowl Family-chat delivery failed: %s", err)
        else:
            self.last_family_delivery = "accepted"

    def _build_family_message(
        self,
        right_needed: bool,
        left_needed: bool,
        right_result: str,
        left_result: str,
        before: Assessment,
        after: Assessment,
    ) -> str:
        fed = right_result.startswith("sent") or left_result.startswith("sent")
        if right_needed:
            if right_result == "sent_and_completed":
                message = f"🐾 {self.pet_name}: fed 1R — dry bowl was empty."
            elif right_result.startswith("sent"):
                message = (
                    f"⚠️ {self.pet_name}: sent 1R, but feeder completion "
                    "was not confirmed."
                )
            else:
                message = (
                    f"⚠️ {self.pet_name}: dry bowl was empty, but feeding was blocked."
                )
        else:
            message = (
                f"🐾 {self.pet_name}: dry food remains "
                f"({_percent_text(before.dry.fill_percent)})."
            )

        if before.wet.visible and before.wet.level != "unknown":
            message += (
                f" Other food: {before.wet.level}"
                f" ({_percent_text(before.wet.fill_percent)})."
            )

        cat_line = (
            "\nCat seen."
            if fed
            and after.cat_present
            and after.cat_confidence >= self.confidence_threshold
            else ""
        )

        return f"{message}{cat_line}"

    async def _async_record_failure(self, error: Exception | str) -> None:
        self.consecutive_failures += 1
        self.last_error = " ".join(str(error).split())[:255]
        if self.consecutive_failures == 1 or self.consecutive_failures % 6 == 0:
            _LOGGER.warning(
                "Cat bowl check failed (%s consecutive): %s",
                self.consecutive_failures,
                self.last_error,
            )
        await self._async_save()
        self._notify()

    def _cycle_payload(self) -> dict[str, Any]:
        return {
            "cycle_key": self.last_cycle_key,
            "status": self.last_cycle_status,
            "feed_result": self.last_feed_result,
            "dry_level": self.bowls["dry"]["raw_level"],
            "wet_level": self.bowls["wet"]["raw_level"],
            "family_delivery": self.last_family_delivery,
        }

    def _baseline_payload(self, status: str) -> dict[str, Any]:
        return {
            "status": status,
            "feeding_sensor": self.feeding_sensor,
            "feed_completed_at": _iso(self.last_feeder_completion_at),
            "baseline_at": _iso(self.baseline_at),
            "baseline_reason": self.baseline_reason,
        }

    def _event_payload(self, bowl_name: str | None = None) -> dict[str, Any]:
        return {
            "camera_entity": self.camera_entity,
            "light_entity": self.light_entity,
            "bowl": bowl_name,
            "dry": dict(self.bowls["dry"]),
            "wet": dict(self.bowls["wet"]),
            "summary": self.summary,
            "checked_at": (
                self.last_checked_at.isoformat() if self.last_checked_at else None
            ),
        }

    @staticmethod
    def _cycle_key(moment: datetime) -> str:
        return dt_util.as_local(moment).strftime("%Y-%m-%d-%H%M")

    async def _async_restore(self) -> None:
        loaded = await self._store.async_load()
        if isinstance(loaded, dict):
            for name in ("dry", "wet"):
                saved = loaded.get(name)
                if isinstance(saved, dict):
                    self.bowls[name].update(
                        {key: saved[key] for key in self.bowls[name] if key in saved}
                    )
            self.summary = str(loaded.get("summary", ""))[:500]
            self.last_model = str(loaded.get("last_model", ""))[:100]
            self.check_count = max(0, int(loaded.get("check_count", 0)))
            self.last_cycle_key = str(loaded.get("last_cycle_key", ""))
            self.last_cycle_status = str(loaded.get("last_cycle_status", "never_run"))
            self.last_cycle_message = str(loaded.get("last_cycle_message", ""))[:1500]
            self.last_feed_result = str(loaded.get("last_feed_result", "not_requested"))
            self.last_family_delivery = str(loaded.get("last_family_delivery", ""))
            self.last_success_at = _parse_datetime(loaded.get("last_success_at"))
            self.last_checked_at = _parse_datetime(loaded.get("last_checked_at"))
            self.last_cycle_at = _parse_datetime(loaded.get("last_cycle_at"))
            self.baseline_at = _parse_datetime(loaded.get("baseline_at"))
            self.baseline_reason = str(loaded.get("baseline_reason", ""))[:80]
            self.last_feeder_completion_at = _parse_datetime(
                loaded.get("last_feeder_completion_at")
            )
            self.pending_feed_baseline_at = _parse_datetime(
                loaded.get("pending_feed_baseline_at")
            )
            self.consumption_from_at = _parse_datetime(
                loaded.get("consumption_from_at")
            )
            self.consumption_to_at = _parse_datetime(loaded.get("consumption_to_at"))
            consumption = loaded.get("consumption")
            self.consumption_baseline_reason = str(
                loaded.get("consumption_baseline_reason", "")
            )[:80]
            if isinstance(consumption, dict):
                self.consumption = Consumption(
                    consumption.get("dry_eaten_percent"),
                    consumption.get("wet_eaten_percent"),
                    float(consumption.get("confidence", 0)),
                    str(consumption.get("summary", ""))[:500],
                )
        for slot in ("latest", "before", "after", "baseline"):
            path = self._image_path(slot)
            if not path.is_file():
                continue
            try:
                content = await self.hass.async_add_executor_job(path.read_bytes)
                self.latest_images[slot] = content
                self.image_updated[slot] = datetime.fromtimestamp(
                    path.stat().st_mtime, tz=dt_util.UTC
                )
            except OSError:
                _LOGGER.warning("Could not restore bowl image %s", slot)

    async def _async_save(self) -> None:
        await self._store.async_save(
            {
                "dry": self.bowls["dry"],
                "wet": self.bowls["wet"],
                "summary": self.summary,
                "last_model": self.last_model,
                "check_count": self.check_count,
                "last_success_at": _iso(self.last_success_at),
                "last_checked_at": _iso(self.last_checked_at),
                "last_cycle_key": self.last_cycle_key,
                "last_cycle_at": _iso(self.last_cycle_at),
                "last_cycle_status": self.last_cycle_status,
                "last_cycle_message": self.last_cycle_message,
                "last_feed_result": self.last_feed_result,
                "last_family_delivery": self.last_family_delivery,
                "baseline_at": _iso(self.baseline_at),
                "baseline_reason": self.baseline_reason,
                "last_feeder_completion_at": _iso(self.last_feeder_completion_at),
                "pending_feed_baseline_at": _iso(self.pending_feed_baseline_at),
                "consumption_from_at": _iso(self.consumption_from_at),
                "consumption_to_at": _iso(self.consumption_to_at),
                "consumption_baseline_reason": self.consumption_baseline_reason,
                "consumption": (
                    {
                        "dry_eaten_percent": self.consumption.dry_eaten_percent,
                        "wet_eaten_percent": self.consumption.wet_eaten_percent,
                        "confidence": self.consumption.confidence,
                        "summary": self.consumption.summary,
                    }
                    if self.consumption
                    else None
                ),
            }
        )

    def _image_path(self, slot: str) -> Path:
        return self._image_directory / f"{slot}.jpg"

    def _write_image(self, slot: str, content: bytes) -> None:
        self._image_directory.mkdir(parents=True, exist_ok=True)
        path = self._image_path(slot)
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(content)
        os.replace(temporary, path)

    def _remove_image(self, slot: str) -> None:
        with suppress(FileNotFoundError):
            self._image_path(slot).unlink()


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt_util.UTC)


def _parse_time(value: Any) -> time:
    """Parse a configured HH:MM time, falling back safely."""
    try:
        return time.fromisoformat(str(value))
    except ValueError:
        return time.fromisoformat(DEFAULT_MORNING_TIME)


def _percent_text(value: int | None) -> str:
    return "unknown" if value is None else f"{value}%"
