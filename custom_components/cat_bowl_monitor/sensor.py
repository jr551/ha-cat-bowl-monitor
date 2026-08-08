"""Sensors for Cat Bowl Monitor."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BowlConfigEntry
from .ai import ProviderError, provider_settings_from_config
from .entity import BowlEntity
from .runtime import BowlRuntime


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BowlConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    runtime = entry.runtime_data
    async_add_entities(
        [
            BowlStatusSensor(runtime, "dry"),
            BowlFillSensor(runtime, "dry"),
            BowlStatusSensor(runtime, "wet"),
            BowlFillSensor(runtime, "wet"),
            ConsumptionSensor(runtime),
            AutoFeedSensor(runtime),
        ]
    )


class BowlStatusSensor(BowlEntity, SensorEntity):
    """Confirmed status for one bowl."""

    def __init__(self, runtime: BowlRuntime, bowl_name: str) -> None:
        super().__init__(runtime)
        self.bowl_name = bowl_name
        self._attr_name = f"{bowl_name.title()} bowl status"
        self._attr_unique_id = f"{runtime.entry.entry_id}_{bowl_name}_status"

    @property
    def native_value(self) -> str:
        return self.runtime.bowl(self.bowl_name)["stable_level"]

    @property
    def icon(self) -> str:
        return {
            "empty": "mdi:bowl-outline",
            "low": "mdi:bowl-mix-outline",
            "okay": "mdi:bowl-mix",
        }.get(self.native_value, "mdi:help-circle-outline")

    @property
    def extra_state_attributes(self) -> dict:
        bowl = self.runtime.bowl(self.bowl_name)
        try:
            provider_source = provider_settings_from_config(
                self.runtime.hass, self.runtime.options
            ).source
        except ProviderError:
            provider_source = "Unavailable"
        return {
            "observed_level": bowl["raw_level"],
            "confidence": bowl["confidence"],
            "visible": bowl["visible"],
            "summary": self.runtime.summary or None,
            "candidate_level": bowl["candidate_level"],
            "candidate_count": bowl["candidate_count"],
            "required_samples": self.runtime.required_samples,
            "confidence_threshold": self.runtime.confidence_threshold,
            "camera_entity": self.runtime.camera_entity,
            "light_entity": self.runtime.light_entity,
            "last_checked_at": (
                self.runtime.last_checked_at.isoformat()
                if self.runtime.last_checked_at
                else None
            ),
            "last_success_at": (
                self.runtime.last_success_at.isoformat()
                if self.runtime.last_success_at
                else None
            ),
            "consecutive_failures": self.runtime.consecutive_failures,
            "last_error": self.runtime.last_error or None,
            "provider_source": provider_source,
            "model": self.runtime.last_model or None,
            "check_count": self.runtime.check_count,
            "schedule": ", ".join(
                scheduled.strftime("%H:%M") for scheduled in self.runtime.schedule_times
            ),
            "image_retention": "latest before/after cycle only",
        }


class BowlFillSensor(BowlEntity, SensorEntity):
    """Latest estimated fill percentage for one bowl."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:gauge"

    def __init__(self, runtime: BowlRuntime, bowl_name: str) -> None:
        super().__init__(runtime)
        self.bowl_name = bowl_name
        self._attr_name = f"{bowl_name.title()} bowl fill"
        self._attr_unique_id = f"{runtime.entry.entry_id}_{bowl_name}_fill"

    @property
    def native_value(self) -> int | None:
        return self.runtime.bowl(self.bowl_name)["fill_percent"]


class ConsumptionSensor(BowlEntity, SensorEntity):
    """Estimated dry-food consumption since the prior scheduled reference."""

    _attr_name = "Food eaten"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:food-drumstick-off"

    def __init__(self, runtime: BowlRuntime) -> None:
        super().__init__(runtime)
        self._attr_unique_id = f"{runtime.entry.entry_id}_food_eaten"

    @property
    def native_value(self) -> int | None:
        if self.runtime.consumption is None:
            return None
        return self.runtime.consumption.dry_eaten_percent

    @property
    def extra_state_attributes(self) -> dict:
        result = self.runtime.consumption
        return {
            "dry_eaten_percent": (result.dry_eaten_percent if result else None),
            "wet_eaten_percent": (result.wet_eaten_percent if result else None),
            "confidence": result.confidence if result else None,
            "summary": result.summary if result else None,
            "baseline_at": (
                self.runtime.consumption_from_at.isoformat()
                if self.runtime.consumption_from_at
                else None
            ),
            "current_at": (
                self.runtime.consumption_to_at.isoformat()
                if self.runtime.consumption_to_at
                else None
            ),
            "baseline_reason": self.runtime.baseline_reason or None,
            "comparison_reference": (self.runtime.consumption_baseline_reason or None),
            "last_feeder_completion_at": (
                self.runtime.last_feeder_completion_at.isoformat()
                if self.runtime.last_feeder_completion_at
                else None
            ),
            "baseline_reset_pending": (
                self.runtime.pending_feed_baseline_at is not None
            ),
        }


class AutoFeedSensor(BowlEntity, SensorEntity):
    """Last closed-loop cycle status."""

    _attr_name = "Auto feed"
    _attr_icon = "mdi:food-drumstick"

    def __init__(self, runtime: BowlRuntime) -> None:
        super().__init__(runtime)
        self._attr_unique_id = f"{runtime.entry.entry_id}_auto_feed"

    @property
    def native_value(self) -> str:
        return self.runtime.last_cycle_status

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "last_cycle_at": (
                self.runtime.last_cycle_at.isoformat()
                if self.runtime.last_cycle_at
                else None
            ),
            "last_cycle_key": self.runtime.last_cycle_key or None,
            "last_feed_result": self.runtime.last_feed_result,
            "family_delivery": self.runtime.last_family_delivery or None,
            "message": self.runtime.last_cycle_message or None,
            "right_feed_entity": self.runtime.right_feed_entity or None,
            "left_feed_entity": self.runtime.left_feed_entity or None,
            "fail_closed": True,
        }
