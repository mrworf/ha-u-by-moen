"""Config flow for U by Moen integration."""

import logging
from typing import Any

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import MoenApi, MoenApiError, MoenAuthError
from .const import DOMAIN
from .coordinator import MoenDataUpdateCoordinator
from .outlets import outlet_label
from .presets import (
    MAX_PRESETS,
    PresetConflictError,
    PresetValidationError,
    clamp_preset_temperatures,
    create_preset,
    move_preset,
    preset_fingerprint,
    preset_from_form,
    replace_preset,
    validate_presets,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class MoenConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for U by Moen."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return the preset-management options flow."""
        return MoenOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate the credentials
            session = async_get_clientsession(self.hass)
            api = MoenApi(
                user_input[CONF_EMAIL],
                user_input[CONF_PASSWORD],
                session,
            )

            try:
                # Try to authenticate
                await api.authenticate()

                # Get devices to verify connection works
                await api.get_devices()

                # Create a unique ID based on the email
                await self.async_set_unique_id(user_input[CONF_EMAIL].lower())
                self._abort_if_unique_id_configured()

                # Create the entry
                return self.async_create_entry(
                    title=f"U by Moen ({user_input[CONF_EMAIL]})",
                    data=user_input,
                )

            except MoenAuthError:
                errors["base"] = "invalid_auth"
            except MoenApiError:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception during setup")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )


class MoenOptionsFlow(config_entries.OptionsFlow):
    """Manage per-device shower presets without storing duplicate options."""

    def __init__(self) -> None:
        self._serial_number: str | None = None
        self._baseline: list[dict[str, Any]] = []
        self._baseline_fingerprint = ""
        self._selected_position: int | None = None
        self._status = ""

    @property
    def _coordinator(self) -> MoenDataUpdateCoordinator:
        return self.hass.data[DOMAIN][self.config_entry.entry_id]["coordinator"]

    @property
    def _device(self) -> dict[str, Any]:
        if self._serial_number is None:
            return {}
        return self._coordinator.devices[self._serial_number]

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Select a shower when the account contains more than one."""
        devices = self._coordinator.devices
        if len(devices) == 1:
            self._serial_number = next(iter(devices))
            return await self.async_step_preset_menu()
        if user_input is not None:
            self._serial_number = user_input["serial_number"]
            return await self.async_step_preset_menu()
        choices = {
            serial: details.get("name", f"Moen Shower {serial}")
            for serial, details in devices.items()
        }
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({vol.Required("serial_number"): vol.In(choices)}),
        )

    async def async_step_preset_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Show available preset operations."""
        presets = self._device.get("presets", [])
        summary = ", ".join(
            f"{preset.get('position')}: {preset.get('title', 'Preset')}"
            for preset in presets
        )
        options = ["edit", "delete", "move"]
        if len(presets) < MAX_PRESETS:
            options.insert(0, "create")
        options.append("finish")
        return self.async_show_menu(
            step_id="preset_menu",
            menu_options=options,
            description_placeholders={
                "device": self._device.get("name", self._serial_number or ""),
                "presets": summary,
                "status": self._status,
            },
        )

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Close the action-oriented options flow."""
        return self.async_create_entry(title="", data={})

    def _capture_baseline(self) -> None:
        presets = self._device.get("presets", [])
        self._baseline = [dict(preset) for preset in presets]
        self._baseline_fingerprint = preset_fingerprint(presets)

    def _preset_choices(self) -> dict[int, str]:
        return {
            int(preset["position"]): (
                f"{preset['position']}: {preset.get('title', 'Preset')}"
            )
            for preset in self._baseline
        }

    async def async_step_create(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Create a preset."""
        if not self._baseline:
            self._capture_baseline()
        defaults = self._new_preset_defaults()
        if user_input is not None:
            try:
                preset = preset_from_form(
                    user_input,
                    self._device.get("outlets", []),
                    position=len(self._baseline) + 1,
                )
                updated = create_preset(self._baseline, preset)
                return await self._async_save_presets(updated, "create", user_input)
            except PresetValidationError as err:
                return self._show_preset_form("create", user_input, err.code)
        return self._show_preset_form("create", defaults)

    async def async_step_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Select a preset to edit."""
        if not self._baseline:
            self._capture_baseline()
        if user_input is not None:
            self._selected_position = int(user_input["position"])
            return await self.async_step_edit_preset()
        return self.async_show_form(
            step_id="edit",
            data_schema=vol.Schema(
                {vol.Required("position"): vol.In(self._preset_choices())}
            ),
        )

    async def async_step_edit_preset(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Edit all settings for one preset."""
        position = self._selected_position or 0
        preset = next(
            item for item in self._baseline if item.get("position") == position
        )
        defaults = self._form_defaults(preset)
        if user_input is not None:
            try:
                replacement = preset_from_form(
                    user_input,
                    self._device.get("outlets", []),
                    position=position,
                )
                updated = replace_preset(self._baseline, position, replacement)
                return await self._async_save_presets(
                    updated, "edit_preset", user_input
                )
            except PresetValidationError as err:
                return self._show_preset_form("edit_preset", user_input, err.code)
        return self._show_preset_form("edit_preset", defaults)

    async def async_step_delete(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Select a preset to delete."""
        if not self._baseline:
            self._capture_baseline()
        if user_input is not None:
            self._selected_position = int(user_input["position"])
            return await self.async_step_delete_confirm()
        return self.async_show_form(
            step_id="delete",
            data_schema=vol.Schema(
                {vol.Required("position"): vol.In(self._preset_choices())}
            ),
        )

    async def async_step_delete_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm and execute preset deletion."""
        position = self._selected_position or 0
        preset = next(
            item for item in self._baseline if item.get("position") == position
        )
        if user_input is not None:
            try:
                result = await self._coordinator.async_delete_preset(
                    self._serial_number or "",
                    self._baseline_fingerprint,
                    position,
                )
                return await self._mutation_complete(result.controller_synced)
            except (PresetConflictError, PresetValidationError, MoenApiError) as err:
                self._log_preset_api_error("delete", err)
                if isinstance(err, PresetConflictError):
                    self._capture_baseline()
                    if not any(
                        item.get("position") == position for item in self._baseline
                    ):
                        self._selected_position = None
                        self._status = "Preset list changed; select a preset again."
                        return await self.async_step_preset_menu()
                return self.async_show_form(
                    step_id="delete_confirm",
                    data_schema=vol.Schema({}),
                    errors={"base": self._error_key(err)},
                    description_placeholders={"preset": preset.get("title", "")},
                )
        return self.async_show_form(
            step_id="delete_confirm",
            data_schema=vol.Schema({}),
            description_placeholders={"preset": preset.get("title", "")},
        )

    async def async_step_move(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Move a preset to a new position."""
        if not self._baseline:
            self._capture_baseline()
        choices = self._preset_choices()
        if user_input is not None:
            try:
                updated = move_preset(
                    self._baseline,
                    int(user_input["position"]),
                    int(user_input["destination"]),
                )
                return await self._async_save_presets(updated, "move", user_input)
            except PresetValidationError as err:
                return self.async_show_form(
                    step_id="move",
                    data_schema=self._move_schema(choices, user_input),
                    errors={"base": err.code},
                )
        return self.async_show_form(
            step_id="move", data_schema=self._move_schema(choices)
        )

    @staticmethod
    def _move_schema(
        choices: dict[int, str], defaults: dict[str, Any] | None = None
    ) -> vol.Schema:
        values = defaults or {}
        return vol.Schema(
            {
                vol.Required(
                    "position", default=values.get("position", next(iter(choices)))
                ): vol.In(choices),
                vol.Required(
                    "destination",
                    default=values.get("destination", next(iter(choices))),
                ): vol.In(choices),
            }
        )

    async def _async_save_presets(
        self,
        presets: list[dict[str, Any]],
        error_step: str,
        submitted: dict[str, Any],
    ) -> FlowResult:
        try:
            mutation = (
                "move"
                if error_step == "move"
                else "edit" if error_step == "edit_preset" else "create"
            )
            candidate = (
                clamp_preset_temperatures(
                    presets, int(self._device.get("max_temp", 115))
                )
                if mutation == "move"
                else presets
            )
            validate_presets(
                candidate,
                max_temperature=int(self._device.get("max_temp", 115)),
                single_outlet_mode=bool(self._device.get("single_outlet_mode", False)),
            )
            result = await self._coordinator.async_replace_presets(
                self._serial_number or "",
                self._baseline_fingerprint,
                candidate,
                mutation,
            )
            return await self._mutation_complete(result.controller_synced)
        except (PresetConflictError, PresetValidationError, MoenApiError) as err:
            operation = "edit" if error_step == "edit_preset" else error_step
            self._log_preset_api_error(operation, err)
            if isinstance(err, PresetConflictError):
                self._capture_baseline()
            if error_step == "move":
                return self.async_show_form(
                    step_id="move",
                    data_schema=self._move_schema(self._preset_choices(), submitted),
                    errors={"base": self._error_key(err)},
                )
            return self._show_preset_form(error_step, submitted, self._error_key(err))

    async def _mutation_complete(self, controller_synced: bool) -> FlowResult:
        self._baseline = []
        self._selected_position = None
        self._status = (
            "Saved and synchronized with the controller."
            if controller_synced
            else "Saved to Moen; controller synchronization is pending."
        )
        return await self.async_step_preset_menu()

    @staticmethod
    def _error_key(err: Exception) -> str:
        if isinstance(err, PresetConflictError):
            return "preset_conflict"
        if isinstance(err, PresetValidationError):
            return err.code
        return "cannot_connect"

    def _log_preset_api_error(self, operation: str, err: Exception) -> None:
        """Log safe service diagnostics while preserving specific form errors."""
        if not isinstance(err, MoenApiError):
            return
        serial_number = self._serial_number or "unknown"
        _LOGGER.warning(
            "Preset %s failed for device %s: %s",
            operation,
            serial_number,
            err,
        )

    def _new_preset_defaults(self) -> dict[str, Any]:
        return {
            "title": "Preset",
            "greeting": "",
            "target_temperature": min(100, int(self._device.get("max_temp", 115))),
            "outlets": [str(self._device.get("outlets", [{}])[0].get("position", 1))],
            "ready_pauses_water": False,
            "ready_pushes_notification": False,
            "ready_sounds_alert": True,
            "timer_enabled": False,
            "timer_minutes": 0,
            "timer_seconds": 0,
            "timer_ends_shower": False,
            "timer_sounds_alert": True,
        }

    @staticmethod
    def _form_defaults(preset: dict[str, Any]) -> dict[str, Any]:
        timer_length = int(preset.get("timer_length", 0))
        return {
            **preset,
            "target_temperature": int(preset.get("target_temperature", 100)),
            "outlets": [
                str(outlet["position"])
                for outlet in preset.get("outlets", [])
                if outlet.get("active")
            ],
            "timer_minutes": timer_length // 60,
            "timer_seconds": timer_length % 60,
        }

    def _show_preset_form(
        self,
        step_id: str,
        defaults: dict[str, Any],
        error: str | None = None,
    ) -> FlowResult:
        temperatures = {
            str(value): self._temperature_label(value)
            for value in range(60, int(self._device.get("max_temp", 115)) + 1)
        }
        outlets = {
            str(outlet["position"]): outlet_label(outlet)
            for outlet in self._device.get("outlets", [])
        }
        schema = vol.Schema(
            {
                vol.Required("title", default=defaults.get("title", "")): str,
                vol.Optional(
                    "greeting", default=defaults.get("greeting", "") or ""
                ): str,
                vol.Required(
                    "target_temperature",
                    default=str(defaults.get("target_temperature", 100)),
                ): vol.In(temperatures),
                vol.Required(
                    "outlets", default=defaults.get("outlets", [])
                ): cv.multi_select(outlets),
                vol.Required(
                    "ready_sounds_alert",
                    default=bool(defaults.get("ready_sounds_alert", True)),
                ): bool,
                vol.Required(
                    "ready_pushes_notification",
                    default=bool(defaults.get("ready_pushes_notification", False)),
                ): bool,
                vol.Required(
                    "ready_pauses_water",
                    default=bool(defaults.get("ready_pauses_water", False)),
                ): bool,
                vol.Required(
                    "timer_enabled",
                    default=bool(defaults.get("timer_enabled", False)),
                ): bool,
                vol.Required(
                    "timer_minutes", default=int(defaults.get("timer_minutes", 0))
                ): vol.All(int, vol.Range(min=0, max=59)),
                vol.Required(
                    "timer_seconds", default=int(defaults.get("timer_seconds", 0))
                ): vol.All(int, vol.Range(min=0, max=59)),
                vol.Required(
                    "timer_sounds_alert",
                    default=bool(defaults.get("timer_sounds_alert", True)),
                ): bool,
                vol.Required(
                    "timer_ends_shower",
                    default=bool(defaults.get("timer_ends_shower", False)),
                ): bool,
            }
        )
        return self.async_show_form(
            step_id=step_id,
            data_schema=schema,
            errors={"base": error} if error else {},
        )

    def _temperature_label(self, fahrenheit: int) -> str:
        unit = self.hass.config.units.temperature_unit
        if str(unit) in ("°C", "C"):
            return f"{(fahrenheit - 32) * 5 / 9:.1f} °C"
        return f"{fahrenheit} °F"
