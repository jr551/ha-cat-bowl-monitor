"""Shared Cat Bowl Monitor entity."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .runtime import BowlRuntime


class BowlEntity(Entity):
    """Base entity tied to one bowl monitor entry."""

    _attr_has_entity_name = True

    def __init__(self, runtime: BowlRuntime) -> None:
        self.runtime = runtime
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, runtime.entry.entry_id)},
            name=runtime.entry.title,
            manufacturer="Cat Bowl Monitor",
            model="AI bowl monitor",
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.runtime.add_listener(self.async_write_ha_state))

    @property
    def available(self) -> bool:
        return self.runtime.available
