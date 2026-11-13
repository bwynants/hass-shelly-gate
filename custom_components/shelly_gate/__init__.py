"""The Shelly Gate integration.

Drives a cover whose operator has a single momentary trigger (one relay,
one press) and gives no position feedback. The travel is dead-reckoned from
a timer, and a physical wall button is followed rather than fought: a press
on it moves the model without sending a pulse of our own.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

PLATFORMS: list[Platform] = [Platform.BUTTON, Platform.COVER]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a Shelly Gate from a config entry."""
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_on_update))
    return True


async def _async_reload_on_update(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Re-read the timings and entity choices by reloading the entry.

    Scheduled rather than awaited: awaiting a reload from inside the listener
    that the reload itself tears down is what HA warns about.
    """
    hass.config_entries.async_schedule_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Tear down."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
