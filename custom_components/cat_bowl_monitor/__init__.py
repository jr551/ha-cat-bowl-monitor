"""Cat Bowl Monitor integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import PLATFORMS
from .runtime import BowlRuntime

type BowlConfigEntry = ConfigEntry[BowlRuntime]


async def async_setup_entry(hass: HomeAssistant, entry: BowlConfigEntry) -> bool:
    """Set up Cat Bowl Monitor from a config entry."""
    runtime = BowlRuntime(hass, entry)
    entry.runtime_data = runtime
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await runtime.async_start()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: BowlConfigEntry) -> bool:
    """Unload one Cat Bowl Monitor entry."""
    await entry.runtime_data.async_stop()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_entry(hass: HomeAssistant, entry: BowlConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
