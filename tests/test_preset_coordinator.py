"""Tests for authoritative preset mutation and controller synchronization."""

import asyncio
import logging

import pytest

from custom_components.u_by_moen.coordinator import MoenDataUpdateCoordinator
from custom_components.u_by_moen.presets import (
    PresetConflictError,
    PresetValidationError,
    preset_fingerprint,
)
from custom_components.u_by_moen.pusher import MoenPusherNotReady


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


def device(presets):
    """Return complete-enough device details for preset mutation."""
    return {
        "serial_number": "SERIAL",
        "name": "Main",
        "api_server": "server",
        "max_temp": 115,
        "single_outlet_mode": False,
        "outlets": preset(1)["outlets"],
        "presets": presets,
    }


class FakeApi:
    """Provide ordered snapshots and capture writes."""

    def __init__(self, snapshots):
        self.snapshots = [device(values) for values in snapshots]
        self.updated = []
        self.deleted = []

    async def get_device_details(self, _serial):
        return self.snapshots.pop(0)

    async def update_presets(self, serial, details, presets):
        self.updated.append((serial, details, presets))

    async def delete_preset(self, serial, position):
        self.deleted.append((serial, position))


class DisconnectedPusher:
    """Reject all controller sync attempts."""

    async def send_client_event(self, *_args):
        raise MoenPusherNotReady("offline")

    async def request_report(self, _serial):
        raise AssertionError("report should not be requested")


class CapturingPusher:
    """Capture non-control synchronization payloads."""

    def __init__(self):
        self.sent = asyncio.Event()
        self.messages = []
        self.reports = 0

    async def send_client_event(self, serial, event, payload):
        self.messages.append((serial, event, payload))
        self.sent.set()

    async def request_report(self, _serial):
        self.reports += 1


def coordinator(api, pusher, initial):
    """Construct a coordinator without a Home Assistant installation."""
    result = object.__new__(MoenDataUpdateCoordinator)
    result.api = api
    result.pusher = pusher
    result.devices = {"SERIAL": device(initial)}
    result.data = result.devices
    result._push_waiters = {}
    result._push_fresh = set()
    result._command_locks = {}
    result._preset_locks = {}
    result._preset_sync_locks = {}
    result._controller_sync_needed = set()
    return result


@pytest.mark.asyncio
async def test_cloud_update_survives_controller_sync_failure() -> None:
    original = [preset(1, "One"), preset(2, "Two")]
    updated = [preset(1, "Morning"), preset(2, "Two")]
    api = FakeApi([original, updated])
    instance = coordinator(api, DisconnectedPusher(), original)

    result = await instance.async_replace_presets(
        "SERIAL", preset_fingerprint(original), updated
    )

    assert result.controller_synced is False
    assert api.updated[0][2] == updated
    assert instance.devices["SERIAL"]["presets"] == updated
    assert "SERIAL" in instance._controller_sync_needed


@pytest.mark.asyncio
async def test_successful_cloud_update_logs_safe_lifecycle(caplog) -> None:
    original = [preset(1, "One"), preset(2, "Two")]
    updated = [preset(1, "Sensitive preset title"), preset(2, "Two")]
    api = FakeApi([original, updated])
    instance = coordinator(api, DisconnectedPusher(), original)

    with caplog.at_level(
        logging.DEBUG, logger="custom_components.u_by_moen.coordinator"
    ):
        await instance.async_replace_presets(
            "SERIAL", preset_fingerprint(original), updated
        )

    assert "Starting preset replacement for device SERIAL (2 presets)" in caplog.text
    assert "Cloud preset replacement accepted for SERIAL" in caplog.text
    assert "Refreshed SERIAL after preset replacement" in caplog.text
    assert "controller sync pending" in caplog.text
    assert "Sensitive preset title" not in caplog.text


@pytest.mark.asyncio
async def test_stale_preset_baseline_prevents_write() -> None:
    original = [preset(1, "One"), preset(2, "Two")]
    externally_changed = [preset(1, "Changed"), preset(2, "Two")]
    api = FakeApi([externally_changed])
    instance = coordinator(api, DisconnectedPusher(), original)

    with pytest.raises(PresetConflictError):
        await instance.async_replace_presets(
            "SERIAL", preset_fingerprint(original), original
        )

    assert api.updated == []


@pytest.mark.asyncio
async def test_delete_preserves_two_preset_minimum() -> None:
    original = [preset(1, "One"), preset(2, "Two")]
    api = FakeApi([original])
    instance = coordinator(api, DisconnectedPusher(), original)

    with pytest.raises(PresetValidationError, match="minimum_presets"):
        await instance.async_delete_preset("SERIAL", preset_fingerprint(original), 1)

    assert api.deleted == []


@pytest.mark.asyncio
async def test_delete_refreshes_authoritative_cloud_list() -> None:
    original = [preset(1, "One"), preset(2, "Two"), preset(3, "Three")]
    refreshed = [preset(1, "One"), preset(2, "Three")]
    api = FakeApi([original, refreshed])
    instance = coordinator(api, DisconnectedPusher(), original)

    result = await instance.async_delete_preset(
        "SERIAL", preset_fingerprint(original), 2
    )

    assert result.controller_synced is False
    assert api.deleted == [("SERIAL", 2)]
    assert instance.devices["SERIAL"]["presets"] == refreshed


@pytest.mark.asyncio
async def test_controller_sync_uses_only_first_two_and_confirms() -> None:
    presets = [preset(1, "One"), preset(2, "Two"), preset(3, "Three")]
    pusher = CapturingPusher()
    instance = coordinator(FakeApi([]), pusher, presets)

    task = asyncio.create_task(
        instance._async_sync_controller_presets("SERIAL", presets)
    )
    await pusher.sent.wait()
    waiter = next(iter(instance._push_waiters["SERIAL"]))
    waiter.put_nowait({"presets": presets[:2]})

    assert await task is True
    assert pusher.messages == [
        (
            "SERIAL",
            "client-state-desired",
            {"type": "preset", "data": presets[:2]},
        )
    ]
    assert pusher.reports == 1
