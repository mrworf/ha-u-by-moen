"""Tests for Pusher state normalization and merging."""

import json

from custom_components.u_by_moen.state import (
    merge_device_update,
    merge_rest_snapshot,
    parse_state_event,
)


def test_parse_string_encoded_state_event_uses_time_remaining() -> None:
    payload = json.dumps(
        {
            "type": "state_change",
            "data": json.dumps(
                {
                    "current_mode": "ready",
                    "time_remaining": 321,
                    "target_temperature": 102,
                }
            ),
        }
    )

    event_type, update = parse_state_event(payload)

    assert event_type == "state_change"
    assert update == {
        "mode": "ready",
        "time_remaining": 321,
        "target_temperature": 102,
    }
    assert "timer_remaining" not in update


def test_partial_outlet_update_preserves_metadata() -> None:
    existing = {
        "outlets": [
            {"position": 1, "active": False, "icon_index": 2, "name": "Hand"},
            {"position": 2, "active": True, "icon_index": 1, "name": "Rain"},
        ]
    }

    merged = merge_device_update(
        existing,
        {"outlets": [{"position": 1, "active": True}]},
    )

    assert merged["outlets"] == [
        {"position": 1, "active": True, "icon_index": 2, "name": "Hand"}
    ]


def test_healthy_push_state_is_not_regressed_by_rest() -> None:
    existing = {
        "name": "Old name",
        "mode": "ready",
        "target_temperature": 103,
        "time_remaining": 120,
    }
    rest = {
        "name": "New name",
        "mode": "off",
        "target_temperature": 98,
        "time_remaining": 0,
    }

    assert merge_rest_snapshot(existing, rest, True) == {
        "name": "New name",
        "mode": "ready",
        "target_temperature": 103,
        "time_remaining": 120,
    }
    assert merge_rest_snapshot(existing, rest, False) == rest


def test_malformed_state_event_is_ignored() -> None:
    assert parse_state_event("not-json") == (None, {})
    assert parse_state_event({"type": "state_change", "data": []}) == (
        "state_change",
        {},
    )
