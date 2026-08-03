"""Bounded diagnostic sample cameras for Cat Bowl Monitor."""

from __future__ import annotations

from homeassistant.components.camera import Camera
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
    runtime = entry.runtime_data
    async_add_entities(
        [
            BowlSampleCamera(runtime, "latest", "Latest AI sample"),
            BowlSampleCamera(runtime, "before", "Before feed sample"),
            BowlSampleCamera(runtime, "after", "After feed sample"),
        ]
    )


class BowlSampleCamera(BowlEntity, Camera):
    """Expose one bounded diagnostic image slot."""

    _attr_icon = "mdi:camera-clock"

    def __init__(self, runtime: BowlRuntime, slot: str, name: str) -> None:
        Camera.__init__(self)
        BowlEntity.__init__(self, runtime)
        self.slot = slot
        self._attr_name = name
        self._attr_unique_id = f"{runtime.entry.entry_id}_{slot}_sample"

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        return self.runtime.latest_images.get(self.slot)

    @property
    def extra_state_attributes(self) -> dict:
        updated = self.runtime.image_updated.get(self.slot)
        return {
            "captured_at": updated.isoformat() if updated else None,
            "retention": "overwritten by the next scheduled cycle",
            "source_entity": self.runtime.camera_entity,
        }
