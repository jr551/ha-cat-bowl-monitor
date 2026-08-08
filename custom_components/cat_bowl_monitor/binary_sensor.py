"""Binary sensors for Cat Bowl Monitor."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
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
            BowlEmptyBinarySensor(runtime, "dry"),
            BowlEmptyBinarySensor(runtime, "wet"),
        ]
    )


class BowlEmptyBinarySensor(BowlEntity, BinarySensorEntity):
    """Confirmed empty state for one bowl."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, runtime: BowlRuntime, bowl_name: str) -> None:
        super().__init__(runtime)
        self.bowl_name = bowl_name
        label = "Primary dry" if bowl_name == "dry" else "Secondary food"
        self._attr_name = f"{label} empty"
        self._attr_unique_id = f"{runtime.entry.entry_id}_{bowl_name}_empty"

    @property
    def is_on(self) -> bool:
        return self.runtime.bowl(self.bowl_name)["stable_level"] == "empty"

    @property
    def icon(self) -> str:
        return "mdi:bowl-outline" if self.is_on else "mdi:bowl-mix"
