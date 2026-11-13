"""Button platform for Shelly Gate.

One button per gate that flips the cover's model between open and closed
without pulsing the operator. It is the replacement for toggling the
`input_boolean` the YAML version kept its state in: the way to put Home
Assistant right after the gate was moved behind its back.
"""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import flip_signal


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the flip button for this config entry."""
    async_add_entities([ShellyGateFlipButton(entry)])


class ShellyGateFlipButton(ButtonEntity):
    """Flips the modelled state of one gate; the gate itself does not move."""

    _attr_has_entity_name = False
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:swap-vertical"

    def __init__(self, entry: ConfigEntry) -> None:
        """Tie the button to its gate."""
        self._entry_id = entry.entry_id
        self._attr_unique_id = f"{entry.entry_id}_flip"
        self._attr_name = f"{entry.title} Flip State"

    async def async_press(self) -> None:
        """Ask the cover to flip its model."""
        async_dispatcher_send(self.hass, flip_signal(self._entry_id))
