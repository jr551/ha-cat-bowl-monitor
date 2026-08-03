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
    async_add_entities([BowlCheckButton(entry.runtime_data)])


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
