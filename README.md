# U by Moen Home Assistant Integration

A custom Home Assistant integration for U by Moen smart showers using an
Alexa/Android account. HomeKit-only systems are not supported.

## Project Status

Core shower controls from Home Assistant and timely sensor updates have been
verified with a live shower.

> [!WARNING]
> The preset manager is implemented and covered by offline, APK-derived
> protocol tests, but creating, editing, deleting, reordering, and synchronizing
> presets with the physical controller have not yet been tested on live
> hardware. Treat preset management as experimental and use it only when you
> can verify the result in the Moen app and on the controller.

## Features

- Control shower power and target temperature through a climate entity.
- Control shower power and individual water outlets through switches.
- Activate configured presets with one button per preset.
- Create, edit, delete, and reorder presets from the integration's Configure
  flow.
- Monitor mode, temperatures, active preset, timer, firmware, preset inventory,
  and complete preset settings.
- Receive timely state updates through the same authenticated Pusher WebSocket
  path used by the Android app.
- Recover state after disconnects through reconnect, resubscribe, full-state
  reports, and REST refreshes.

This is a cloud-push integration. Home Assistant must be able to reach the Moen
API and Pusher service; local-LAN control is not implemented.

## Installation

### HACS (recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=WeaveHubHQ&repository=ha-u-by-moen)

1. Open HACS and select **Integrations**.
2. Open the menu in the upper-right corner and select **Custom repositories**.
3. Add this repository URL with the category **Integration**.
4. Install **U by Moen** and restart Home Assistant.

### Manual installation

1. Copy `custom_components/u_by_moen` into your Home Assistant
   `config/custom_components/` directory.
2. Restart Home Assistant.

## Configuration

1. Go to **Settings** → **Devices & services**.
2. Select **Add integration** and search for **U by Moen**.
3. Enter the email address and password for your U by Moen Alexa/Android
   account.
4. Submit the form. Showers on the account are discovered automatically.

## Using the Integration

### Shower controls

- Use the climate entity to start or stop the shower and set its target
  temperature.
- Use the power switch for direct on/off control.
- Use the outlet switches to enable or disable individual shower heads, hand
  showers, tub spouts, or body sprays.
- Press a preset button to activate the preset currently assigned to that
  position.

Entity IDs are assigned by Home Assistant and may differ from the examples in
this document.

### Experimental preset management

Open **Settings** → **Devices & services**, find **U by Moen**, and select
**Configure**. Accounts with multiple showers are prompted to choose a device;
single-shower accounts open the preset menu directly.

The flow can perform several operations before you select **Finish**:

- Create a preset.
- Edit an existing preset.
- Delete a preset.
- Move a preset to another position.

Each preset includes its title, greeting, target temperature, active outlets,
ready alerts, ready pause behavior, timer duration, timer alert, and timer end
behavior. Temperatures are displayed in Home Assistant's configured unit while
the exact Fahrenheit value expected by Moen is preserved.

A shower must retain at least 2 presets and supports at most 10. Positions 1
and 2 correspond to the presets on the physical controller, so moving presets
into or out of those positions changes the intended controller assignments.

The integration checks for concurrent preset changes before writing so an old
form cannot silently replace a newer preset list. After a successful cloud
update, it attempts to synchronize positions 1 and 2 to the controller. If that
step is temporarily unavailable, the cloud change remains saved and controller
synchronization is retried after reconnecting.

Preset writes and controller synchronization described above have not yet been
validated against live hardware.

## Entity Reference

The integration creates the following entities for each discovered shower:

| Domain | Example | Purpose |
| --- | --- | --- |
| Climate | `climate.master_bathroom` | Shower power, current temperature, and target temperature |
| Switch | `switch.master_bathroom_power` | Direct shower power control |
| Switch | `switch.master_bathroom_hand_shower` | One switch per available water outlet |
| Button | `button.master_bathroom_morning` | Activate the preset assigned to a position |
| Sensor | `sensor.master_bathroom_mode` | Current shower mode |
| Sensor | `sensor.master_bathroom_current_temperature` | Current water temperature |
| Sensor | `sensor.master_bathroom_target_temperature` | Requested water temperature |
| Sensor | `sensor.master_bathroom_active_preset` | Active preset title or `None` |
| Sensor | `sensor.master_bathroom_time_remaining` | Remaining preset timer duration |
| Sensor | `sensor.master_bathroom_firmware` | Controller firmware version |
| Sensor | `sensor.master_bathroom_preset_count` | Preset count and ordered position/title inventory |
| Sensor | `sensor.master_bathroom_preset_1_details` | Title and complete settings for one preset position |

Preset buttons and detail sensors are added or removed as preset positions
change. Their identities remain tied to positions, so moving a preset changes
the title and settings represented by the corresponding position entities.

The preset-count sensor has a compact `presets` attribute containing each
preset's `position` and `title`. Each preset-detail sensor uses the preset title
as its state and exposes these attributes:

- `position` and `greeting`
- `target_temperature` and `temperature_unit`
- Complete ordered `outlets` metadata
- `ready_pauses_water`, `ready_pushes_notification`, and
  `ready_sounds_alert`
- `timer_enabled`, `timer_length`, `timer_ends_shower`, and
  `timer_sounds_alert`

Preset-detail temperatures use Home Assistant's configured display unit.

## Examples

### Start the shower at a target temperature

```yaml
automation:
  - alias: "Morning shower"
    triggers:
      - trigger: time
        at: "06:30:00"
    actions:
      - action: climate.set_temperature
        target:
          entity_id: climate.master_bathroom
        data:
          temperature: 102
          hvac_mode: heat
```

### Activate a preset

```yaml
automation:
  - alias: "Activate morning shower preset"
    triggers:
      - trigger: state
        entity_id: binary_sensor.someone_home
        to: "on"
    actions:
      - action: button.press
        target:
          entity_id: button.master_bathroom_morning
```

### Dashboard card

```yaml
type: entities
title: Master Bathroom Shower
entities:
  - entity: climate.master_bathroom
  - entity: sensor.master_bathroom_mode
  - entity: sensor.master_bathroom_current_temperature
  - entity: sensor.master_bathroom_active_preset
  - entity: sensor.master_bathroom_preset_count
  - entity: sensor.master_bathroom_preset_1_details
  - type: divider
  - entity: button.master_bathroom_morning
  - type: divider
  - entity: switch.master_bathroom_shower_head
  - entity: switch.master_bathroom_hand_shower
```

## How Synchronization Works

- The Moen REST API provides authentication, device discovery, initial state,
  recovery state, and cloud preset persistence.
- Authenticated, device-scoped Pusher channels carry commands and live shower
  state. The connection is supervised with heartbeat, reconnect, resubscribe,
  and a full-state request after subscription.
- While Pusher is healthy, an older REST response cannot overwrite newer live
  shower state.
- Preset positions 1 and 2 are sent to the controller with a settings message,
  not a preset-activation command. This preset synchronization behavior is
  based on the Android protocol and offline tests but remains unverified on a
  live controller.

## Known Limitations

- Moen cloud and Pusher availability are required for control and updates.
- The APK's local-LAN control path is not implemented.
- Preset creation, editing, deletion, reordering, and controller
  synchronization are not yet live-tested.
- This integration targets Alexa/Android accounts, not HomeKit-only systems.

## Troubleshooting

### Integration does not appear

- Confirm `custom_components/u_by_moen` is installed in the Home Assistant
  configuration directory.
- Restart Home Assistant after installing or upgrading the integration.

### Authentication fails

- Verify the email address and password in the U by Moen app.
- Confirm the account belongs to the Alexa/Android version of U by Moen rather
  than a HomeKit-only system.

### Controls are unavailable or updates are delayed

- Confirm Home Assistant has internet access.
- Check the Home Assistant logs for Moen API, Pusher authorization,
  subscription, or reconnect errors.
- Reload the integration to force fresh authentication, REST state recovery,
  and Pusher subscription.

### Preset management fails

- Remember that the preset flow has not yet been tested on live hardware.
- Check the Home Assistant log for `Preset create failed`, `Preset edit failed`,
  `Preset move failed`, or `Preset delete failed`. The warning includes the
  request method, endpoint, HTTP status, optional Moen request ID, and a
  truncated response with credential-like fields automatically redacted.
- Reopen **Configure** before retrying if Home Assistant reports that the preset
  list changed while a form was open.
- Verify the resulting preset list in the Moen app and on the controller.
- A message that controller synchronization is pending means the cloud update
  succeeded but the controller has not confirmed positions 1 and 2; the
  integration retries after Pusher reconnects.

### Enable debug logging

Add the following to `configuration.yaml` and restart Home Assistant:

```yaml
logger:
  default: info
  logs:
    custom_components.u_by_moen: debug
```

When sharing logs, redact email addresses, passwords, account tokens, shower
tokens, and Pusher authorization values. The integration redacts known secret
fields from preset error responses, but review logs for personal information
before posting them publicly.

## API Information

- **Base URL:** `https://www.moen-iot.com`
- **Authentication:** Email/password exchange for API tokens
- **Real-time transport:** Device-scoped Pusher credentials and authenticated
  private channels

## Contributing

Contributions and live-device preset test reports are welcome. Please open an
issue or pull request and remove all credentials and tokens from logs or
captures.

Come see our other apps and integrations at [WeaveHub](https://weavehub.app).

### Development setup

1. Clone the repository.
2. Install dependencies with `pip install -r requirements.txt`.
3. Make the change.
4. Run `pytest -q` and `ruff check custom_components/u_by_moen tests`.
5. Test behavior with Home Assistant where safe and applicable.

## License

MIT License — see [LICENSE](LICENSE).

## Credits

Created by Jason Lazerus.

## Disclaimer

This is an unofficial integration and is not affiliated with or endorsed by
Moen or Fortune Brands.
