"""Tests for preset validation and transformation."""

import pytest

from custom_components.u_by_moen.presets import (
    PresetValidationError,
    create_preset,
    move_preset,
    preset_detail_attributes,
    preset_from_form,
    preset_inventory,
    preset_slots,
    replace_preset,
    validate_presets,
)


def preset(position: int, title: str = "Preset") -> dict:
    """Return one complete test preset."""
    return {
        "position": position,
        "title": title,
        "greeting": "Hello",
        "target_temperature": 100,
        "outlets": [
            {"position": 1, "active": True, "icon_index": 2},
            {"position": 2, "active": False, "icon_index": 3},
        ],
        "ready_pauses_water": False,
        "ready_pushes_notification": True,
        "ready_sounds_alert": True,
        "timer_enabled": True,
        "timer_length": 615,
        "timer_ends_shower": True,
        "timer_sounds_alert": True,
    }


def test_create_replace_and_move_presets_normalize_positions() -> None:
    original = [preset(1, "One"), preset(2, "Two")]
    created = create_preset(original, preset(-1, "Three"))
    replaced = replace_preset(created, 2, preset(99, "Second"))
    moved = move_preset(replaced, 3, 1)

    assert [item["position"] for item in moved] == [1, 2, 3]
    assert [item["title"] for item in moved] == ["Three", "One", "Second"]
    assert [item["title"] for item in original] == ["One", "Two"]


def test_form_preserves_outlet_metadata_and_timer_fields() -> None:
    form = {
        "title": " Evening ",
        "greeting": "Sam",
        "target_temperature": "103",
        "outlets": ["2"],
        "ready_pauses_water": True,
        "ready_pushes_notification": False,
        "ready_sounds_alert": True,
        "timer_enabled": True,
        "timer_minutes": 7,
        "timer_seconds": 5,
        "timer_ends_shower": True,
        "timer_sounds_alert": False,
    }
    outlets = [
        {"position": 1, "active": True, "icon_index": 2},
        {"position": 2, "active": False, "icon_index": 7},
    ]

    built = preset_from_form(form, outlets, position=3)

    assert built["title"] == "Evening"
    assert built["timer_length"] == 425
    assert built["outlets"] == [
        {"position": 1, "active": False, "icon_index": 2},
        {"position": 2, "active": True, "icon_index": 7},
    ]


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"title": ""}, "title_required"),
        ({"target_temperature": 116}, "invalid_temperature"),
        ({"timer_length": 3600}, "invalid_timer"),
        ({"outlets": [{"position": 1, "active": False}]}, "invalid_outlets"),
    ],
)
def test_validation_rejects_invalid_fields(change, code) -> None:
    values = [preset(1, "One"), preset(2, "Two")]
    values[0].update(change)

    with pytest.raises(PresetValidationError) as raised:
        validate_presets(values, max_temperature=115, single_outlet_mode=False)

    assert raised.value.code == code


def test_single_outlet_mode_rejects_multiple_active_outlets() -> None:
    values = [preset(1, "One"), preset(2, "Two")]
    values[0]["outlets"][1]["active"] = True

    with pytest.raises(PresetValidationError, match="invalid_outlets"):
        validate_presets(values, max_temperature=115, single_outlet_mode=True)


def test_preset_slots_drive_dynamic_entity_add_and_remove() -> None:
    before = {"SERIAL": {"presets": [preset(1), preset(2)]}}
    after = {"SERIAL": {"presets": [preset(1), preset(3)]}}

    existing = preset_slots(before)
    desired = preset_slots(after)

    assert desired - existing == {("SERIAL", 3)}
    assert existing - desired == {("SERIAL", 2)}


def test_create_rejects_android_ten_preset_limit() -> None:
    values = [preset(position, str(position)) for position in range(1, 11)]

    with pytest.raises(PresetValidationError, match="preset_limit"):
        create_preset(values, preset(-1, "Eleven"))


def test_inventory_is_ordered_and_compact() -> None:
    values = [
        preset(2, "Two"),
        {"position": "invalid", "title": "Ignored"},
        preset(1, "One"),
    ]

    assert preset_inventory(values) == [
        {"position": 1, "title": "One"},
        {"position": 2, "title": "Two"},
    ]


def test_detail_attributes_expose_all_settings_in_home_assistant_units() -> None:
    values = preset(1, "Morning")

    details = preset_detail_attributes(values, "°C")

    assert details == {
        "position": 1,
        "greeting": "Hello",
        "target_temperature": 37.8,
        "temperature_unit": "°C",
        "outlets": [
            {
                "position": 1,
                "active": True,
                "icon_index": 2,
                "name": "Hand Shower",
            },
            {
                "position": 2,
                "active": False,
                "icon_index": 3,
                "name": "Body Spray",
            },
        ],
        "ready_pauses_water": False,
        "ready_pushes_notification": True,
        "ready_sounds_alert": True,
        "timer_enabled": True,
        "timer_length": 615,
        "timer_ends_shower": True,
        "timer_sounds_alert": True,
    }


def test_detail_attributes_tolerate_missing_optional_data() -> None:
    details = preset_detail_attributes(
        {
            "position": 4,
            "target_temperature": 101,
            "outlets": "invalid",
            "timer_length": True,
        },
        "°F",
    )

    assert details["target_temperature"] == 101
    assert details["temperature_unit"] == "°F"
    assert details["outlets"] == []
    assert details["timer_length"] == 0
    assert details["ready_sounds_alert"] is False
