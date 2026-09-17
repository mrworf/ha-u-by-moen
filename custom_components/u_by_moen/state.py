"""Pure state normalization helpers for U by Moen."""

from __future__ import annotations

import json
from typing import Any

VOLATILE_FIELDS = frozenset(
    {
        "mode",
        "current_temperature",
        "target_temperature",
        "outlets",
        "active_preset",
        "timer_enabled",
        "time_remaining",
    }
)


def _decode(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def parse_state_event(payload: Any) -> tuple[str | None, dict[str, Any]]:
    """Normalize an APK-style client-state-reported payload."""
    envelope = _decode(payload)
    if not isinstance(envelope, dict):
        return None, {}
    event_type = envelope.get("type")
    body = _decode(envelope.get("data", {}))
    if not isinstance(body, dict):
        body = {}
    update: dict[str, Any] = {}
    aliases = {
        "current_mode": "mode",
        "current_temperature": "current_temperature",
        "target_temperature": "target_temperature",
        "outlets": "outlets",
        "active_preset": "active_preset",
        "timer_enabled": "timer_enabled",
        "time_remaining": "time_remaining",
        "presets": "presets",
        "battery_level": "battery_level",
        "timer_length": "timer_length",
        "timer_ends_shower": "timer_ends_shower",
        "timer_sounds_alert": "timer_sounds_alert",
        "ready_pauses_water": "ready_pauses_water",
        "ready_pushes_notification": "ready_pushes_notification",
        "ready_sounds_alert": "ready_sounds_alert",
        "title": "preset_title",
        "greeting": "preset_greeting",
    }
    for source, target in aliases.items():
        if source in body:
            update[target] = body[source]
    if "current_firmware_version" in envelope:
        update["current_firmware_version"] = envelope["current_firmware_version"]
    return event_type if isinstance(event_type, str) else None, update


def _merge_outlets(
    existing: list[dict[str, Any]], incoming: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    by_position = {
        item.get("position"): dict(item)
        for item in existing
        if isinstance(item, dict) and item.get("position") is not None
    }
    result: list[dict[str, Any]] = []
    for item in incoming:
        if not isinstance(item, dict):
            continue
        merged = dict(by_position.get(item.get("position"), {}))
        merged.update(item)
        result.append(merged)
    return result


def merge_device_update(
    existing: dict[str, Any], update: dict[str, Any]
) -> dict[str, Any]:
    """Merge a partial device update while preserving outlet metadata."""
    merged = dict(existing)
    for key, value in update.items():
        merged[key] = (
            _merge_outlets(existing.get("outlets", []), value)
            if key == "outlets" and isinstance(value, list)
            else value
        )
    return merged


def merge_rest_snapshot(
    existing: dict[str, Any], snapshot: dict[str, Any], push_is_fresh: bool
) -> dict[str, Any]:
    """Merge REST metadata without regressing push-owned volatile state."""
    if not push_is_fresh:
        return dict(snapshot)
    merged = dict(existing)
    for key, value in snapshot.items():
        if key not in VOLATILE_FIELDS:
            merged[key] = value
    return merged
