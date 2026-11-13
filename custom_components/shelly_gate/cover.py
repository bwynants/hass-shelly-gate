"""Cover platform for Shelly Gate.

The operator this drives has one momentary input and no feedback: every press
advances it through open -> stop -> close -> stop -> open. So the entity keeps
that cycle as a model, dead-reckons the position from the configured travel
times, and turns `open`/`close`/`set_position` into however many presses the
cycle needs to end up travelling the requested way.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from homeassistant.components.cover import (
    ATTR_CURRENT_POSITION,
    ATTR_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_CLOSING,
    STATE_OPEN,
    STATE_OPENING,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.restore_state import ExtraStoredData, RestoreEntity

from .const import (
    CONF_BUTTON_ENTITY,
    CONF_DEVICE_CLASS,
    CONF_PULSE_GAP_SECONDS,
    CONF_PULSE_SECONDS,
    CONF_TRAVEL_DOWN_SECONDS,
    CONF_TRAVEL_UP_SECONDS,
    CONF_TRIGGER_ENTITY,
    DEFAULT_DEVICE_CLASS,
    DEFAULT_PULSE_GAP_SECONDS,
    DEFAULT_PULSE_SECONDS,
    DEFAULT_TRAVEL_SECONDS,
    MAX_PRESSES,
    POSITION_EPSILON,
    PRESSABLE_DOMAINS,
    TICK,
    flip_signal,
)

_LOGGER = logging.getLogger(__name__)

UP = 1
DOWN = -1
IDLE = 0

ATTR_LAST_DIRECTION = "last_direction"


class ShellyGateExtraData(ExtraStoredData):
    """The bit of state a restored `current_position` cannot express.

    A cover stopped half way moves in whichever direction it was *not* going
    last time, so that direction has to survive a restart alongside the
    position.
    """

    def __init__(self, last_direction: int) -> None:
        """Hold the direction of the last completed movement."""
        self.last_direction = last_direction

    def as_dict(self) -> dict[str, Any]:
        """Serialise for the restore-state store."""
        return {ATTR_LAST_DIRECTION: self.last_direction}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the cover for this config entry."""
    async_add_entities([ShellyGateCover(entry)])


class ShellyGateCover(CoverEntity, RestoreEntity):
    """A cover behind a single momentary trigger."""

    _attr_has_entity_name = False
    _attr_should_poll = False
    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
        | CoverEntityFeature.SET_POSITION
    )

    def __init__(self, entry: ConfigEntry) -> None:
        """Read the entry's settings and start from a fully closed cover."""
        settings = {**entry.data, **entry.options}

        self._entry_id = entry.entry_id
        self._attr_unique_id = entry.entry_id
        self._attr_name = entry.title
        self._attr_device_class = CoverDeviceClass(
            settings.get(CONF_DEVICE_CLASS, DEFAULT_DEVICE_CLASS)
        )

        self._trigger_entity: str = settings[CONF_TRIGGER_ENTITY]
        self._button_entity: str | None = settings.get(CONF_BUTTON_ENTITY) or None
        self._pulse = float(settings.get(CONF_PULSE_SECONDS, DEFAULT_PULSE_SECONDS))
        self._gap = float(
            settings.get(CONF_PULSE_GAP_SECONDS, DEFAULT_PULSE_GAP_SECONDS)
        )
        self._travel_up = float(
            settings.get(CONF_TRAVEL_UP_SECONDS, DEFAULT_TRAVEL_SECONDS)
        )
        self._travel_down = float(
            settings.get(CONF_TRAVEL_DOWN_SECONDS, DEFAULT_TRAVEL_SECONDS)
        )

        # Dead-reckoning state.
        self._position = 0.0
        self._direction = IDLE
        self._last_direction = DOWN
        self._target: float | None = None
        self._travel_started = 0.0
        self._travel_started_at = 0.0
        self._unsub_tick: Any = None

        # Serialises the multi-press command sequences against each other and
        # against a wall-button press arriving mid-sequence.
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    @property
    def current_cover_position(self) -> int:
        """Dead-reckoned position, 0 closed to 100 open."""
        return int(round(self._position))

    @property
    def is_closed(self) -> bool:
        """Whether the cover is at its bottom end stop."""
        return self._position <= POSITION_EPSILON

    @property
    def is_opening(self) -> bool:
        """Whether the cover is travelling up."""
        return self._direction == UP

    @property
    def is_closing(self) -> bool:
        """Whether the cover is travelling down."""
        return self._direction == DOWN

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose what the next press would do, which is otherwise invisible."""
        next_direction = self._press_direction() if not self._direction else IDLE
        return {
            "next_press": {UP: "open", DOWN: "close", IDLE: "stop"}[next_direction],
            "trigger_entity": self._trigger_entity,
        }

    @property
    def extra_restore_state_data(self) -> ShellyGateExtraData:
        """Persist the direction of the last movement."""
        return ShellyGateExtraData(self._last_direction)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_added_to_hass(self) -> None:
        """Restore the position and start following the trigger and button."""
        await super().async_added_to_hass()
        await self._async_restore()

        self._async_follow_trigger()
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self._trigger_entity], self._async_trigger_changed
            )
        )
        if self._button_entity:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, [self._button_entity], self._async_button_changed
                )
            )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, flip_signal(self._entry_id), self._async_flip_requested
            )
        )
        self.async_on_remove(self._cancel_tick)

    async def _async_restore(self) -> None:
        """Pick up where the last run left off.

        A restart during travel leaves no way to know how far the cover got,
        and the operator almost certainly finished the movement it was given,
        so assume it reached the end stop it was heading for.
        """
        if (last_state := await self.async_get_last_state()) is None:
            return

        if (extra := await self.async_get_last_extra_data()) is not None:
            stored = extra.as_dict().get(ATTR_LAST_DIRECTION)
            if stored in (UP, DOWN):
                self._last_direction = stored

        if last_state.state == STATE_OPENING:
            self._position, self._last_direction = 100.0, UP
        elif last_state.state == STATE_CLOSING:
            self._position, self._last_direction = 0.0, DOWN
        elif (
            stored_position := last_state.attributes.get(ATTR_CURRENT_POSITION)
        ) is not None:
            self._position = min(100.0, max(0.0, float(stored_position)))
        elif last_state.state == STATE_OPEN:
            self._position = 100.0

    # ------------------------------------------------------------------
    # Dead reckoning
    # ------------------------------------------------------------------

    def _refresh_position(self) -> None:
        """Advance the modelled position to now."""
        if not self._direction:
            return
        duration = self._travel_up if self._direction == UP else self._travel_down
        elapsed = time.monotonic() - self._travel_started_at
        moved = elapsed / duration * 100.0 * self._direction
        self._position = min(100.0, max(0.0, self._travel_started + moved))

    def _start_travel(self, direction: int, target: float | None) -> None:
        """Note that the cover has begun moving, and from where."""
        self._refresh_position()
        self._direction = direction
        self._target = target
        self._travel_started = self._position
        self._travel_started_at = time.monotonic()
        self._schedule_tick()

    def _settle(self, snap_to: float | None = None) -> None:
        """Note that the cover has stopped, optionally at an exact position."""
        self._refresh_position()
        if snap_to is not None:
            self._position = snap_to
        if self._direction:
            self._last_direction = self._direction
        self._direction = IDLE
        self._target = None
        self._cancel_tick()

    def _press_direction(self) -> int:
        """Which way a press sends a standing cover.

        At an end stop there is only one way to go; stopped half way, the
        operator reverses whatever it did last.
        """
        if self._position <= POSITION_EPSILON:
            return UP
        if self._position >= 100.0 - POSITION_EPSILON:
            return DOWN
        return -self._last_direction

    def _destination(self) -> float:
        """Where the current movement ends if nothing interrupts it."""
        if self._target is not None:
            return self._target
        return 100.0 if self._direction == UP else 0.0

    # ------------------------------------------------------------------
    # Ticking while in motion
    # ------------------------------------------------------------------

    def _schedule_tick(self) -> None:
        """Start publishing position updates if not already doing so."""
        if self._unsub_tick is None:
            self._unsub_tick = async_track_time_interval(
                self.hass, self._async_tick, TICK
            )

    @callback
    def _cancel_tick(self) -> None:
        """Stop publishing position updates."""
        if self._unsub_tick is not None:
            self._unsub_tick()
            self._unsub_tick = None

    async def _async_tick(self, _now: Any) -> None:
        """Publish the travelling position and finish the movement on arrival."""
        if self._lock.locked():
            # A command sequence owns the model right now; the next tick
            # picks the position back up once it is done.
            return

        async with self._lock:
            if not self._direction:
                self._cancel_tick()
                return

            self._refresh_position()
            destination = self._destination()
            arrived = (
                self._position >= destination - POSITION_EPSILON
                if self._direction == UP
                else self._position <= destination + POSITION_EPSILON
            )
            if arrived:
                # An end stop halts the operator by itself; an intermediate
                # position is only reached by pressing to stop it there.
                needs_press = 0.0 < destination < 100.0
                self._settle(snap_to=destination)
                if needs_press:
                    await self._async_pulse_trigger()

            self.async_write_ha_state()

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        await self._async_travel_to(100.0)

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover."""
        await self._async_travel_to(0.0)

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Travel to a position and press to stop there."""
        await self._async_travel_to(float(kwargs[ATTR_POSITION]))

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the cover, which for this operator is a press while moving."""
        async with self._lock:
            self._refresh_position()
            if not self._direction:
                return
            await self._async_press()
            self.async_write_ha_state()

    async def _async_travel_to(self, target: float) -> None:
        """Press as often as the operator's cycle needs to head for `target`."""
        target = min(100.0, max(0.0, target))

        async with self._lock:
            self._refresh_position()
            if not self._direction and abs(target - self._position) <= 1.0:
                return

            wanted = UP if target > self._position else DOWN

            for _ in range(MAX_PRESSES):
                self._refresh_position()
                if self._direction == wanted:
                    # Already on its way: just decide where to stop it.
                    self._target = target if 0.0 < target < 100.0 else None
                    self.async_write_ha_state()
                    return

                await self._async_press()
                self.async_write_ha_state()
                # Give the operator time to act on the press before deciding
                # what the next one would do.
                await asyncio.sleep(self._gap)

            _LOGGER.warning(
                "%s did not start moving %s after %d presses of %s",
                self.entity_id,
                "up" if wanted == UP else "down",
                MAX_PRESSES,
                self._trigger_entity,
            )

    async def _async_press(self) -> None:
        """Pulse the trigger and advance the model as the operator would."""
        await self._async_pulse_trigger()
        self._apply_press()

    @callback
    def _apply_press(self) -> None:
        """Advance the model by one press, whoever pressed it."""
        self._refresh_position()
        if self._direction:
            self._settle()
        else:
            self._start_travel(self._press_direction(), None)

    async def _async_pulse_trigger(self) -> None:
        """Poke the operator's input the way its domain expects."""
        domain = self._trigger_entity.split(".", 1)[0]
        target = {ATTR_ENTITY_ID: self._trigger_entity}

        if domain in PRESSABLE_DOMAINS:
            service = (
                "press" if domain in ("button", "input_button") else SERVICE_TURN_ON
            )
            await self.hass.services.async_call(domain, service, target, blocking=True)
            return

        await self.hass.services.async_call(
            domain, SERVICE_TURN_ON, target, blocking=True
        )
        await asyncio.sleep(self._pulse)
        await self.hass.services.async_call(
            domain, SERVICE_TURN_OFF, target, blocking=True
        )

    # ------------------------------------------------------------------
    # Following the outside world
    # ------------------------------------------------------------------

    @callback
    def _async_follow_trigger(self) -> None:
        """A cover we cannot drive is not available."""
        state = self.hass.states.get(self._trigger_entity)
        self._attr_available = state is not None and state.state not in (
            STATE_UNAVAILABLE,
            STATE_UNKNOWN,
        )

    @callback
    def _async_trigger_changed(self, _event: Event[EventStateChangedData]) -> None:
        """Track whether the trigger entity can still be driven."""
        self._async_follow_trigger()
        self.async_write_ha_state()

    @callback
    def _async_button_changed(self, event: Event[EventStateChangedData]) -> None:
        """Follow a press on the physical button.

        The operator has already acted on it, so this only moves the model —
        pulsing here would be a second press and undo the first.
        """
        new_state = event.data["new_state"]
        old_state = event.data["old_state"]
        if new_state is None or new_state.state != "on":
            return
        if old_state is not None and old_state.state == "on":
            return

        self.hass.async_create_task(self._async_apply_external_press())

    async def _async_apply_external_press(self) -> None:
        """Apply an external press without stepping on a running sequence."""
        async with self._lock:
            self._apply_press()
            self.async_write_ha_state()

    # ------------------------------------------------------------------
    # Correcting a model that has drifted from the real gate
    # ------------------------------------------------------------------

    @callback
    def _async_flip_requested(self) -> None:
        """Handle a press on this gate's flip button."""
        self.hass.async_create_task(self._async_flip())

    async def _async_flip(self) -> None:
        """Turn the model upside down without touching the operator.

        For when a remote control or a missed press has left the gate open
        while the model says closed, or the other way round. Nothing is
        pulsed: closed becomes open, 30 % becomes 70 %, opening becomes
        closing, and the direction a half-way stop remembers is reversed
        with it so the next press is still predicted correctly.
        """
        async with self._lock:
            self._refresh_position()
            self._position = 100.0 - self._position
            if self._direction:
                self._direction = -self._direction
                if self._target is not None:
                    self._target = 100.0 - self._target
                self._travel_started = self._position
                self._travel_started_at = time.monotonic()
            else:
                self._last_direction = -self._last_direction
            self.async_write_ha_state()
