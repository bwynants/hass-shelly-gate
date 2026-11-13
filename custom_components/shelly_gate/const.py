"""Constants for the Shelly Gate integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "shelly_gate"

# Config entry data
CONF_TRIGGER_ENTITY = "trigger_entity"
CONF_BUTTON_ENTITY = "button_entity"
CONF_DEVICE_CLASS = "device_class"

# Config entry options (tunables)
CONF_PULSE_SECONDS = "pulse_seconds"
CONF_PULSE_GAP_SECONDS = "pulse_gap_seconds"
CONF_TRAVEL_UP_SECONDS = "travel_up_seconds"
CONF_TRAVEL_DOWN_SECONDS = "travel_down_seconds"

DEFAULT_DEVICE_CLASS = "garage"
DEFAULT_PULSE_SECONDS = 0.4
DEFAULT_PULSE_GAP_SECONDS = 1.0
DEFAULT_TRAVEL_SECONDS = 30.0

# Domains that can be pulsed (turn_on, wait, turn_off) versus fired once.
PULSABLE_DOMAINS = ("switch", "input_boolean")
PRESSABLE_DOMAINS = ("button", "input_button", "script", "scene")

# How often the dead-reckoned position is published while the cover travels.
TICK = timedelta(seconds=1)

# An operator driven by a single trigger cycles open -> stop -> close -> stop.
# Reaching a chosen direction from the worst starting point costs three
# presses, so allow one more than that before giving up.
MAX_PRESSES = 4

# Positions within this many percent of an end stop count as fully there.
POSITION_EPSILON = 0.5


def flip_signal(entry_id: str) -> str:
    """Dispatcher signal that asks one gate's cover to flip its model."""
    return f"{DOMAIN}_flip_{entry_id}"
