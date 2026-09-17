"""APK-compatible U by Moen control payload builders."""

from __future__ import annotations

import math
from typing import Any


class MoenCommandError(Exception):
    """A control command could not be built or confirmed."""


def control_payload(
    action: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the inner client-state-desired payload used by Android 2.5.0."""
    data: dict[str, Any] = {"action": action}
    if params is not None:
        data["params"] = params
    return {"type": "control", "data": data}


def power_payload(turn_on: bool) -> dict[str, Any]:
    """Build a power or resume payload."""
    if turn_on:
        return control_payload("shower_on", {})
    return control_payload("shower_off")


def preset_payload(
    presets: list[dict[str, Any]],
    position: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build the APK's compact or complete preset activation payload."""
    preset = next(
        (item for item in presets if item.get("position") == position),
        None,
    )
    if preset is None:
        raise MoenCommandError(f"Preset {position} is not available")
    if position <= 2:
        return control_payload("shower_on", {"preset": position}), dict(preset)
    return control_payload("shower_set", dict(preset)), dict(preset)


def temperature_payload(
    temperature: float,
    minimum: float,
    maximum: float,
) -> tuple[dict[str, Any], int]:
    """Validate and build a whole-degree target-temperature payload."""
    if isinstance(temperature, bool) or not isinstance(temperature, (int, float)):
        raise MoenCommandError("Temperature must be numeric")
    if not math.isfinite(temperature) or not minimum <= temperature <= maximum:
        raise MoenCommandError(
            f"Temperature must be between {minimum:g} and {maximum:g}"
        )
    target = round(temperature)
    return control_payload("temperature_set", {"target_temperature": target}), target


def outlet_payload(
    outlets: list[dict[str, Any]],
    position: int,
    active: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Build a full ordered outlet update while preserving device metadata."""
    if not outlets or any(
        not isinstance(outlet, dict)
        or not isinstance(outlet.get("position"), int)
        or not isinstance(outlet.get("active"), bool)
        for outlet in outlets
    ):
        raise MoenCommandError("Current outlet state is incomplete")

    found = False
    updated: list[dict[str, Any]] = []
    for outlet in outlets:
        item = dict(outlet)
        if item["position"] == position:
            item["active"] = active
            found = True
        updated.append(item)
    if not found:
        raise MoenCommandError(f"Outlet {position} is not available")
    return control_payload("outlets_set", {"outlets": updated}), updated
