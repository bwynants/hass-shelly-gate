# Shelly Gate — Home Assistant Custom Integration

A cover for a gate or garage door whose operator has **one momentary input and no
position feedback** — the classic single-button opener wired to a Shelly relay.

Replaces the usual template-cover approach (helpers, a 1-second template sensor
and an automation) with a single entity. Despite the name it is not tied to
Shelly hardware: any entity that can be pulsed or pressed works as the trigger.
Everything runs locally.

## Installation

Requires Home Assistant 2025.2 or newer.
<!-- ha-marketplace:exclude-start -->
[![Open your Home Assistant instance and show this repository in the Marketplace.](https://my.home-assistant.io/badges/marketplace_repository.svg)](https://my.home-assistant.io/redirect/marketplace_repository/?owner=bwynants&repository=hass-shelly-gate&category=integration)

### Marketplace (Home Assistant 2026.11 or newer, recommended)

1. Click the badge above, or open **Settings → Marketplace → Add from link** (top right; the Marketplace needs a GitHub account connected for custom repositories).
2. Add `https://github.com/bwynants/hass-shelly-gate` with type **Integration**.
3. Install **Shelly Gate** and restart Home Assistant.

### HACS (Home Assistant 2026.10 or older)

1. In HACS, open the overflow menu → **Custom repositories**.
2. Add `https://github.com/bwynants/hass-shelly-gate` with type **Integration**.
3. Install **Shelly Gate** and restart Home Assistant.

### Manual installation

1. Copy the `custom_components/shelly_gate/` folder into your HA `config/custom_components/` directory.
2. Restart Home Assistant.
<!-- ha-marketplace:exclude-end -->

## What it models

Every press advances the operator through its own cycle:

| Operator is | A press makes it |
| --- | --- |
| closed | open |
| open | close |
| moving | stop |
| stopped half way | move the *opposite* way to last time |

`open`, `close` and `set_position` are translated into however many presses that
cycle needs — reopening a gate that was stopped on its way up costs three, because
the operator insists on going down, stopping, and only then back up. The position
is dead-reckoned from the configured travel times and republished every second
while moving.

## Setup

Settings → Devices & Services → **Add integration** → Shelly Gate.

| Field | What it is |
| --- | --- |
| Trigger | The output on the operator's push-button input. A `switch` or `input_boolean` is pulsed on then off; a `button`, `input_button`, `script` or `scene` is fired once. |
| Wall button | Optional. The input that reports a press on the physical button. |
| Type | Device class: garage, gate, door, shutter, awning or curtain. |

Then open the entry's options and enter the measured opening time, closing time,
pulse length and inter-pulse gap.

For a garden gate on a Shelly with a detached input, for example:

- Trigger: `switch.garage_tuin_control`
- Wall button: `binary_sensor.garage_tuin_button`
- Opening/closing time: whatever the gate actually takes (the default is 30 s)

## Why the wall button matters

A template cover typically answers a wall-button press with `cover.toggle`, which
pulses the relay a second time and undoes the press. Here a wall-button press only
advances the model — the operator already acted on it, so no pulse is sent.

## When the model is wrong

Each gate also gets a button, `button.<name>_flip_state`. Pressing it turns the
model upside down **without pulsing the operator**: closed becomes open, 30 %
becomes 70 %, opening becomes closing. Use it when the gate was moved behind Home
Assistant's back and the cover shows the opposite of what you see.

## What survives a restart

The position and the direction of the last movement are restored. A restart *during*
travel is assumed to have completed, since the operator keeps running while Home
Assistant is down and there is no sensor to ask.

## Known limits

- Position is dead-reckoned. It drifts if the gate is driven by a remote control or
  by pressing the relay directly, and only resyncs when the gate next reaches an
  end stop. If it ends up showing the opposite end stop, press the flip button.
- Reversing direction from a mid-travel stop makes the gate briefly move the wrong
  way. That is the operator's cycle, not a bug — the presses cannot be skipped.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
