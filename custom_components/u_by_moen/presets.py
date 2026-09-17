"""Preset validation and transformation helpers."""

from __future__ import annotations

import copy
import json
from typing import Any

MIN_PRESETS = 2
MAX_PRESETS = 10
MIN_TEMPERATURE_F = 60
MAX_TIMER_SECONDS = 3599

PRESET_BOOLEAN_FIELDS = (
    "ready_pauses_water",
    "ready_pushes_notification",
    "ready_sounds_alert",
    "timer_enabled",
    "timer_ends_shower",
    "timer_sounds_alert",
)

OUTLET_NAMES = {
    0: "Shower Head",
    1: "Rain Shower",
    2: "Hand Shower",
    3: "Body Spray",
    4: "Valve",
    5: "Water Feature",
    6: "Tub Spout",
}


class PresetError(Exception):
    """Base preset-management error."""


class PresetConflictError(PresetError):
    """The preset list changed after a form was opened."""


class PresetValidationError(PresetError):
    """A preset list or form value is invalid."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def preset_fingerprint(presets: list[dict[str, Any]]) -> str:
    """Return a stable comparison value for a preset list."""
    return json.dumps(presets, sort_keys=True, separators=(",", ":"))


def copy_presets(presets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deep-copy a preset list so forms cannot mutate coordinator state."""
    return copy.deepcopy(presets)


def preset_slots(
    devices: dict[str, dict[str, Any]],
) -> set[tuple[str, int]]:
    """Return all valid serial/position entity slots."""
    return {
        (serial, int(preset["position"]))
        for serial, device in devices.items()
        for preset in device.get("presets", [])
        if isinstance(preset, dict)
        and isinstance(preset.get("position"), int)
        and preset["position"] > 0
    }


def preset_inventory(presets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the compact ordered preset inventory exposed by the count sensor."""
    valid_presets = [
        item
        for item in presets
        if isinstance(item, dict)
        and isinstance(item.get("position"), int)
        and not isinstance(item.get("position"), bool)
    ]
    return [
        {"position": preset["position"], "title": preset.get("title", "Preset")}
        for preset in sorted(valid_presets, key=lambda item: item["position"])
    ]


def preset_detail_attributes(
    preset: dict[str, Any], temperature_unit: str
) -> dict[str, Any]:
    """Return stable, recorder-safe detail attributes for one preset."""
    temperature = preset.get("target_temperature")
    if isinstance(temperature, (int, float)) and not isinstance(temperature, bool):
        displayed_temperature: int | float = temperature
        if temperature_unit in ("°C", "C"):
            displayed_temperature = round((temperature - 32) * 5 / 9, 1)
    else:
        displayed_temperature = None

    outlets = []
    raw_outlets = preset.get("outlets", [])
    if not isinstance(raw_outlets, list):
        raw_outlets = []
    for outlet in raw_outlets:
        if not isinstance(outlet, dict):
            continue
        item = copy.deepcopy(outlet)
        item.setdefault("name", OUTLET_NAMES.get(item.get("icon_index"), "Outlet"))
        outlets.append(item)

    timer_length = preset.get("timer_length")
    return {
        "position": preset.get("position"),
        "greeting": preset.get("greeting"),
        "target_temperature": displayed_temperature,
        "temperature_unit": temperature_unit,
        "outlets": outlets,
        "ready_pauses_water": bool(preset.get("ready_pauses_water", False)),
        "ready_pushes_notification": bool(
            preset.get("ready_pushes_notification", False)
        ),
        "ready_sounds_alert": bool(preset.get("ready_sounds_alert", False)),
        "timer_enabled": bool(preset.get("timer_enabled", False)),
        "timer_length": (
            timer_length
            if isinstance(timer_length, int) and not isinstance(timer_length, bool)
            else 0
        ),
        "timer_ends_shower": bool(preset.get("timer_ends_shower", False)),
        "timer_sounds_alert": bool(preset.get("timer_sounds_alert", False)),
    }


def normalize_positions(
    presets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return deep-copied presets with contiguous one-based positions."""
    normalized = copy_presets(presets)
    for position, preset in enumerate(normalized, start=1):
        preset["position"] = position
    return normalized


def validate_presets(
    presets: list[dict[str, Any]],
    *,
    max_temperature: int,
    single_outlet_mode: bool,
) -> list[dict[str, Any]]:
    """Validate and normalize a complete server preset list."""
    if not MIN_PRESETS <= len(presets) <= MAX_PRESETS:
        raise PresetValidationError("preset_count")
    normalized = normalize_positions(presets)
    for preset in normalized:
        title = preset.get("title")
        if not isinstance(title, str) or not title.strip():
            raise PresetValidationError("title_required")
        preset["title"] = title.strip()
        greeting = preset.get("greeting")
        if greeting is not None and not isinstance(greeting, str):
            raise PresetValidationError("invalid_greeting")

        temperature = preset.get("target_temperature")
        if (
            isinstance(temperature, bool)
            or not isinstance(temperature, int)
            or not MIN_TEMPERATURE_F <= temperature <= max_temperature
        ):
            raise PresetValidationError("invalid_temperature")

        outlets = preset.get("outlets")
        if not isinstance(outlets, list) or not outlets:
            raise PresetValidationError("invalid_outlets")
        if any(
            not isinstance(outlet, dict)
            or not isinstance(outlet.get("position"), int)
            or not isinstance(outlet.get("active"), bool)
            for outlet in outlets
        ):
            raise PresetValidationError("invalid_outlets")
        active_count = sum(bool(outlet["active"]) for outlet in outlets)
        if active_count < 1 or (single_outlet_mode and active_count != 1):
            raise PresetValidationError("invalid_outlets")

        timer_length = preset.get("timer_length")
        if (
            isinstance(timer_length, bool)
            or not isinstance(timer_length, int)
            or not 0 <= timer_length <= MAX_TIMER_SECONDS
        ):
            raise PresetValidationError("invalid_timer")
        for field in PRESET_BOOLEAN_FIELDS:
            if not isinstance(preset.get(field), bool):
                raise PresetValidationError("invalid_boolean")
    return normalized


def create_preset(
    presets: list[dict[str, Any]], preset: dict[str, Any]
) -> list[dict[str, Any]]:
    """Append a new preset and assign its position."""
    if len(presets) >= MAX_PRESETS:
        raise PresetValidationError("preset_limit")
    updated = copy_presets(presets)
    updated.append(copy.deepcopy(preset))
    return normalize_positions(updated)


def replace_preset(
    presets: list[dict[str, Any]],
    position: int,
    preset: dict[str, Any],
) -> list[dict[str, Any]]:
    """Replace one preset position."""
    updated = copy_presets(presets)
    if not 1 <= position <= len(updated):
        raise PresetValidationError("preset_missing")
    replacement = copy.deepcopy(preset)
    replacement["position"] = position
    updated[position - 1] = replacement
    return normalize_positions(updated)


def move_preset(
    presets: list[dict[str, Any]], source: int, destination: int
) -> list[dict[str, Any]]:
    """Move one preset to a new one-based position."""
    if not 1 <= source <= len(presets) or not 1 <= destination <= len(presets):
        raise PresetValidationError("preset_missing")
    updated = copy_presets(presets)
    updated.insert(destination - 1, updated.pop(source - 1))
    return normalize_positions(updated)


def preset_from_form(
    form: dict[str, Any],
    device_outlets: list[dict[str, Any]],
    *,
    position: int,
) -> dict[str, Any]:
    """Build a complete preset while preserving outlet metadata."""
    selected = {int(value) for value in form["outlets"]}
    outlets = []
    for outlet in device_outlets:
        item = copy.deepcopy(outlet)
        item["active"] = item.get("position") in selected
        outlets.append(item)
    return {
        "position": position,
        "title": str(form["title"]).strip(),
        "greeting": str(form.get("greeting", "")),
        "target_temperature": int(form["target_temperature"]),
        "outlets": outlets,
        "ready_pauses_water": bool(form["ready_pauses_water"]),
        "ready_pushes_notification": bool(form["ready_pushes_notification"]),
        "ready_sounds_alert": bool(form["ready_sounds_alert"]),
        "timer_enabled": bool(form["timer_enabled"]),
        "timer_length": int(form["timer_minutes"]) * 60 + int(form["timer_seconds"]),
        "timer_ends_shower": bool(form["timer_ends_shower"]),
        "timer_sounds_alert": bool(form["timer_sounds_alert"]),
    }
