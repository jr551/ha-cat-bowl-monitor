"""Button for Cat Bowl Monitor."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BowlConfigEntry
from .entity import BowlEntity
from .runtime import BowlRuntime


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BowlConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(
        [
            BowlCheckButton(entry.runtime_data),
            BowlCheckAndFeedButton(entry.runtime_data),
            WetFoodAddedButton(entry.runtime_data),
        ]
    )


class BowlCheckButton(BowlEntity, ButtonEntity):
    """Run an immediate AI bowl check."""

    _attr_name = "Check now"
    _attr_icon = "mdi:camera-marker"

    def __init__(self, runtime: BowlRuntime) -> None:
        super().__init__(runtime)
        self._attr_unique_id = f"{runtime.entry.entry_id}_check_now"

    @property
    def available(self) -> bool:
        return self.hass.states.get(self.runtime.camera_entity) is not None

    async def async_press(self) -> None:
        await self.runtime.async_check()


class BowlCheckAndFeedButton(BowlEntity, ButtonEntity):
    """Run an immediate guarded assess-feed-reassess cycle."""

    _attr_name = "Check and feed now"
    _attr_icon = "mdi:bowl-mix"

    def __init__(self, runtime: BowlRuntime) -> None:
        super().__init__(runtime)
        self._attr_unique_id = f"{runtime.entry.entry_id}_check_and_feed_now"

    @property
    def available(self) -> bool:
        return self.hass.states.get(self.runtime.camera_entity) is not None

    async def async_press(self) -> None:
        await self.runtime.async_scheduled_cycle()


class WetFoodAddedButton(BowlEntity, ButtonEntity):
    """Mark the start of a known fresh wet-food batch."""

    _attr_name = "Fresh wet food added"
    _attr_icon = "mdi:food-drumstick"

    def __init__(self, runtime: BowlRuntime) -> None:
        super().__init__(runtime)
        self._attr_unique_id = f"{runtime.entry.entry_id}_fresh_wet_food_added"

    async def async_press(self) -> None:
        await self.runtime.async_mark_wet_food_added()
