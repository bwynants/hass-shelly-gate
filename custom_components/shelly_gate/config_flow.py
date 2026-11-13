"""Config and options flow for the Shelly Gate integration.

Setup is a matter of pointing at the entities that make up the gate: the
momentary output that pokes the operator, and optionally the input that
reports a press on the wall button. The timings live in the options, because
they are calibrated by watching the gate rather than known up front.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.cover import CoverDeviceClass
from homeassistant.const import CONF_NAME
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

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
    DOMAIN,
    PRESSABLE_DOMAINS,
    PULSABLE_DOMAINS,
)

_DEVICE_CLASSES = [
    CoverDeviceClass.GARAGE.value,
    CoverDeviceClass.GATE.value,
    CoverDeviceClass.DOOR.value,
    CoverDeviceClass.SHUTTER.value,
    CoverDeviceClass.AWNING.value,
    CoverDeviceClass.CURTAIN.value,
]

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): TextSelector(),
        vol.Required(CONF_TRIGGER_ENTITY): EntitySelector(
            EntitySelectorConfig(domain=list(PULSABLE_DOMAINS + PRESSABLE_DOMAINS))
        ),
        vol.Optional(CONF_BUTTON_ENTITY): EntitySelector(
            EntitySelectorConfig(domain=["binary_sensor", "input_boolean", "switch"])
        ),
        vol.Required(CONF_DEVICE_CLASS, default=DEFAULT_DEVICE_CLASS): SelectSelector(
            SelectSelectorConfig(
                options=_DEVICE_CLASSES,
                mode=SelectSelectorMode.DROPDOWN,
                translation_key="device_class",
            )
        ),
    }
)


def _seconds(minimum: float, maximum: float, step: float) -> NumberSelector:
    """A seconds field typed in as a number."""
    return NumberSelector(
        NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=step,
            mode=NumberSelectorMode.BOX,
            unit_of_measurement="s",
        )
    )


def _options_schema(options: dict[str, Any]) -> vol.Schema:
    """Build the timings schema, defaulted to the current values."""
    return vol.Schema(
        {
            vol.Required(
                CONF_TRAVEL_UP_SECONDS,
                default=options.get(CONF_TRAVEL_UP_SECONDS, DEFAULT_TRAVEL_SECONDS),
            ): _seconds(1, 600, 0.5),
            vol.Required(
                CONF_TRAVEL_DOWN_SECONDS,
                default=options.get(CONF_TRAVEL_DOWN_SECONDS, DEFAULT_TRAVEL_SECONDS),
            ): _seconds(1, 600, 0.5),
            vol.Required(
                CONF_PULSE_SECONDS,
                default=options.get(CONF_PULSE_SECONDS, DEFAULT_PULSE_SECONDS),
            ): _seconds(0.1, 5, 0.1),
            vol.Required(
                CONF_PULSE_GAP_SECONDS,
                default=options.get(CONF_PULSE_GAP_SECONDS, DEFAULT_PULSE_GAP_SECONDS),
            ): _seconds(0.2, 10, 0.1),
        }
    )


def _clean(user_input: dict[str, Any]) -> dict[str, Any]:
    """Normalise a submitted setup form."""
    data = {
        CONF_NAME: str(user_input[CONF_NAME]).strip(),
        CONF_TRIGGER_ENTITY: user_input[CONF_TRIGGER_ENTITY],
        CONF_DEVICE_CLASS: user_input[CONF_DEVICE_CLASS],
    }
    if button := user_input.get(CONF_BUTTON_ENTITY):
        data[CONF_BUTTON_ENTITY] = button
    return data


class ShellyGateConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask which entities make up the gate."""
        errors: dict[str, str] = {}

        if user_input is not None:
            data = _clean(user_input)
            if data.get(CONF_BUTTON_ENTITY) == data[CONF_TRIGGER_ENTITY]:
                errors[CONF_BUTTON_ENTITY] = "same_entity"
            else:
                self._async_abort_entries_match(
                    {CONF_TRIGGER_ENTITY: data[CONF_TRIGGER_ENTITY]}
                )
                return self.async_create_entry(
                    title=data[CONF_NAME],
                    data=data,
                    options={
                        CONF_TRAVEL_UP_SECONDS: DEFAULT_TRAVEL_SECONDS,
                        CONF_TRAVEL_DOWN_SECONDS: DEFAULT_TRAVEL_SECONDS,
                        CONF_PULSE_SECONDS: DEFAULT_PULSE_SECONDS,
                        CONF_PULSE_GAP_SECONDS: DEFAULT_PULSE_GAP_SECONDS,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                DATA_SCHEMA, user_input or {}
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user repoint the gate at other entities."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            data = _clean(user_input)
            if data.get(CONF_BUTTON_ENTITY) == data[CONF_TRIGGER_ENTITY]:
                errors[CONF_BUTTON_ENTITY] = "same_entity"
            else:
                return self.async_update_reload_and_abort(
                    entry, title=data[CONF_NAME], data=data
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                DATA_SCHEMA, {**entry.data, **(user_input or {})}
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> ShellyGateOptionsFlow:
        """Return the options flow."""
        return ShellyGateOptionsFlow()


class ShellyGateOptionsFlow(OptionsFlow):
    """Timings: travel times, pulse length and the gap between pulses."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show and store the timings."""
        if user_input is not None:
            return self.async_create_entry(
                data={key: float(value) for key, value in user_input.items()}
            )
        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(dict(self.config_entry.options)),
        )
