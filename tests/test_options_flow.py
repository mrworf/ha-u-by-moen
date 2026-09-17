"""Tests for native preset-management options flow behavior."""

import logging
from types import SimpleNamespace

import pytest

from custom_components.u_by_moen.api import MoenApiError, MoenApiHttpError
from custom_components.u_by_moen.config_flow import MoenOptionsFlow
from custom_components.u_by_moen.coordinator import PresetMutationResult
from custom_components.u_by_moen.presets import PresetConflictError


def preset(position, title):
    return {
        "position": position,
        "title": title,
        "greeting": "",
        "target_temperature": 100,
        "outlets": [{"position": 1, "active": True, "icon_index": 2}],
        "ready_pauses_water": False,
        "ready_pushes_notification": False,
        "ready_sounds_alert": True,
        "timer_enabled": False,
        "timer_length": 600,
        "timer_ends_shower": False,
        "timer_sounds_alert": True,
    }


def device(name="Main"):
    return {
        "name": name,
        "max_temp": 115,
        "single_outlet_mode": False,
        "outlets": [{"position": 1, "active": True, "icon_index": 2}],
        "presets": [preset(1, "One"), preset(2, "Two")],
    }


class FakeCoordinator:
    def __init__(self, devices):
        self.devices = devices
        self.replacements = []
        self.conflict = False
        self.api_error = None

    async def async_replace_presets(self, serial, baseline, presets, mutation):
        if self.api_error is not None:
            raise self.api_error
        if self.conflict:
            raise PresetConflictError("changed")
        self.replacements.append((serial, baseline, presets, mutation))
        self.devices[serial]["presets"] = presets
        return PresetMutationResult(True)

    async def async_delete_preset(self, serial, baseline, position):
        if self.api_error is not None:
            raise self.api_error
        self.devices[serial]["presets"].pop(position - 1)
        return PresetMutationResult(True)


def make_flow(devices, unit="°F"):
    coordinator = FakeCoordinator(devices)
    flow = MoenOptionsFlow()
    flow.config_entry = SimpleNamespace(entry_id="entry")
    flow.hass = SimpleNamespace(
        data={"u_by_moen": {"entry": {"coordinator": coordinator}}},
        config=SimpleNamespace(units=SimpleNamespace(temperature_unit=unit)),
    )
    return flow, coordinator


def form_values(title="Three"):
    return {
        "title": title,
        "greeting": "Taylor",
        "target_temperature": "102",
        "outlets": ["1"],
        "ready_pauses_water": True,
        "ready_pushes_notification": False,
        "ready_sounds_alert": True,
        "timer_enabled": True,
        "timer_minutes": 5,
        "timer_seconds": 30,
        "timer_ends_shower": True,
        "timer_sounds_alert": False,
    }


def test_new_preset_defaults_match_android_timer_default() -> None:
    flow, _ = make_flow({"SERIAL": device()})
    flow._serial_number = "SERIAL"

    defaults = flow._new_preset_defaults()

    assert defaults["timer_enabled"] is False
    assert defaults["timer_minutes"] == 0
    assert defaults["timer_seconds"] == 0


@pytest.mark.asyncio
async def test_single_device_create_returns_to_menu() -> None:
    flow, coordinator = make_flow({"SERIAL": device()})

    initial = await flow.async_step_init()
    form = await flow.async_step_create()
    result = await flow.async_step_create(form_values())

    assert initial["type"] == "menu"
    assert form["step_id"] == "create"
    assert result["type"] == "menu"
    assert "synchronized" in result["description_placeholders"]["status"]
    serial, _, presets, mutation = coordinator.replacements[0]
    assert serial == "SERIAL"
    assert mutation == "create"
    assert [item["title"] for item in presets] == ["One", "Two", "Three"]
    assert presets[-1]["timer_length"] == 330


@pytest.mark.asyncio
async def test_multiple_devices_require_selection() -> None:
    flow, _ = make_flow({"ONE": device("One"), "TWO": device("Two")})

    result = await flow.async_step_init()

    assert result["type"] == "form"
    assert result["step_id"] == "init"


@pytest.mark.asyncio
async def test_move_uses_android_contract_and_clamps_to_current_maximum() -> None:
    details = device()
    details["max_temp"] = 99
    flow, coordinator = make_flow({"SERIAL": details})
    await flow.async_step_init()
    await flow.async_step_move()

    result = await flow.async_step_move({"position": 1, "destination": 2})

    assert result["type"] == "menu"
    _, _, presets, mutation = coordinator.replacements[0]
    assert mutation == "move"
    assert all(item["target_temperature"] == 99 for item in presets)


@pytest.mark.asyncio
async def test_conflict_stays_on_form_with_user_values() -> None:
    flow, coordinator = make_flow({"SERIAL": device()})
    await flow.async_step_init()
    await flow.async_step_create()
    coordinator.conflict = True

    result = await flow.async_step_create(form_values("Keep my title"))

    assert result["type"] == "form"
    assert result["errors"] == {"base": "preset_conflict"}
    validated = result["data_schema"](form_values("Keep my title"))
    assert validated["title"] == "Keep my title"


def test_temperature_labels_follow_home_assistant_units() -> None:
    flow, _ = make_flow({"SERIAL": device()}, unit="°C")

    assert flow._temperature_label(100) == "37.8 °C"


async def submit_failed_operation(flow, operation):
    """Submit one options-flow operation after its selection step."""
    await flow.async_step_init()
    if operation == "create":
        await flow.async_step_create()
        return await flow.async_step_create(form_values("Sensitive submitted title"))
    if operation == "edit":
        await flow.async_step_edit()
        await flow.async_step_edit({"position": 1})
        return await flow.async_step_edit_preset(
            form_values("Sensitive submitted title")
        )
    if operation == "move":
        await flow.async_step_move()
        return await flow.async_step_move({"position": 1, "destination": 2})
    await flow.async_step_delete()
    await flow.async_step_delete({"position": 1})
    return await flow.async_step_delete_confirm({})


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create", "edit", "move", "delete"])
async def test_api_failures_log_safe_operation_context(operation, caplog) -> None:
    flow, coordinator = make_flow({"SERIAL": device()})
    method = "DELETE" if operation == "delete" else "PATCH"
    path = (
        "/v2/showers/SERIAL/presets/1"
        if operation == "delete"
        else "/v4/showers/SERIAL"
    )
    coordinator.api_error = MoenApiHttpError(
        method,
        path,
        422,
        '{"error":"server explanation","user_token":"private-token"}',
        "request-123",
    )

    with caplog.at_level(
        logging.WARNING, logger="custom_components.u_by_moen.config_flow"
    ):
        result = await submit_failed_operation(flow, operation)

    assert result["errors"] == {"base": "cannot_connect"}
    assert f"Preset {operation} failed for device SERIAL" in caplog.text
    assert f"{method} {path} returned HTTP 422" in caplog.text
    assert "server explanation" in caplog.text
    assert "request_id=request-123" in caplog.text
    assert "<redacted>" in caplog.text
    assert "private-token" not in caplog.text
    assert "Sensitive submitted title" not in caplog.text


def test_failure_logging_does_not_render_private_exception_cause(caplog) -> None:
    flow, _ = make_flow({"SERIAL": device()})
    flow._serial_number = "SERIAL"
    try:
        raise RuntimeError("private low-level details")
    except RuntimeError as cause:
        error = MoenApiError("safe transport failure")
        error.__cause__ = cause

    with caplog.at_level(
        logging.DEBUG, logger="custom_components.u_by_moen.config_flow"
    ):
        flow._log_preset_api_error("create", error)

    assert "safe transport failure" in caplog.text
    assert "private low-level details" not in caplog.text
