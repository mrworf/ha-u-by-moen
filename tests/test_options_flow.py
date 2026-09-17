"""Tests for native preset-management options flow behavior."""

from types import SimpleNamespace

import pytest

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

    async def async_replace_presets(self, serial, baseline, presets):
        if self.conflict:
            raise PresetConflictError("changed")
        self.replacements.append((serial, baseline, presets))
        self.devices[serial]["presets"] = presets
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
    serial, _, presets = coordinator.replacements[0]
    assert serial == "SERIAL"
    assert [item["title"] for item in presets] == ["One", "Two", "Three"]
    assert presets[-1]["timer_length"] == 330


@pytest.mark.asyncio
async def test_multiple_devices_require_selection() -> None:
    flow, _ = make_flow({"ONE": device("One"), "TWO": device("Two")})

    result = await flow.async_step_init()

    assert result["type"] == "form"
    assert result["step_id"] == "init"


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
