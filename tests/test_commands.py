"""Tests for APK-compatible command construction and confirmation."""

import asyncio
import json

import pytest

from custom_components.u_by_moen.commands import (
    MoenCommandError,
    outlet_payload,
    power_payload,
    preset_payload,
    temperature_payload,
)
from custom_components.u_by_moen.coordinator import MoenDataUpdateCoordinator


def test_power_wire_payloads_match_apk() -> None:
    assert power_payload(True) == {
        "type": "control",
        "data": {"action": "shower_on", "params": {}},
    }
    assert power_payload(False) == {
        "type": "control",
        "data": {"action": "shower_off"},
    }


def test_preset_payload_uses_both_apk_branches() -> None:
    presets = [
        {"position": 1, "title": "One", "target_temperature": 100},
        {"position": 3, "title": "Three", "target_temperature": 104},
    ]

    compact, _ = preset_payload(presets, 1)
    complete, _ = preset_payload(presets, 3)

    assert compact["data"] == {
        "action": "shower_on",
        "params": {"preset": 1},
    }
    assert complete["data"] == {
        "action": "shower_set",
        "params": presets[1],
    }
    with pytest.raises(MoenCommandError):
        preset_payload(presets, 2)


def test_temperature_and_outlet_payloads_validate_and_preserve_metadata() -> None:
    temperature, target = temperature_payload(101.4, 60, 115)
    assert target == 101
    assert temperature["data"]["params"] == {"target_temperature": 101}
    with pytest.raises(MoenCommandError):
        temperature_payload(116, 60, 115)

    outlets = [
        {"position": 1, "active": False, "icon_index": 2},
        {"position": 2, "active": True, "icon_index": 1},
    ]
    payload, updated = outlet_payload(outlets, 1, True)
    assert updated == [
        {"position": 1, "active": True, "icon_index": 2},
        {"position": 2, "active": True, "icon_index": 1},
    ]
    assert payload["data"]["params"]["outlets"] == updated
    with pytest.raises(MoenCommandError):
        outlet_payload([{"position": 1}], 1, True)


class FakePusher:
    """Capture commands without opening a WebSocket."""

    def __init__(self) -> None:
        self.sent = asyncio.Event()
        self.messages = []
        self.report_requests = 0

    async def send_client_event(self, serial, event, payload) -> None:
        self.messages.append((serial, event, payload))
        self.sent.set()

    async def request_report(self, _serial) -> None:
        self.report_requests += 1


class FakeApi:
    """Return a configured fallback snapshot."""

    def __init__(self, snapshot) -> None:
        self.snapshot = snapshot

    async def get_device_details(self, _serial):
        return dict(self.snapshot)


def make_coordinator(snapshot):
    coordinator = object.__new__(MoenDataUpdateCoordinator)
    coordinator.devices = {"SERIAL": {"serial_number": "SERIAL", "mode": "off"}}
    coordinator.data = coordinator.devices
    coordinator.pusher = FakePusher()
    coordinator.api = FakeApi(snapshot)
    coordinator._push_waiters = {}
    coordinator._push_fresh = set()
    coordinator._command_locks = {}
    return coordinator


@pytest.mark.asyncio
async def test_command_uses_json_string_wire_data_and_confirms_from_push() -> None:
    coordinator = make_coordinator({"serial_number": "SERIAL", "mode": "off"})
    task = asyncio.create_task(coordinator.async_set_power("SERIAL", True))
    await coordinator.pusher.sent.wait()

    serial, event, payload = coordinator.pusher.messages[0]
    assert (serial, event) == ("SERIAL", "client-state-desired")
    # The transport performs this exact JSON encoding for Pusher's outer data.
    assert json.loads(json.dumps(payload, separators=(",", ":"))) == payload

    waiter = next(iter(coordinator._push_waiters["SERIAL"]))
    waiter.put_nowait({"mode": "adjusting"})
    await task
    assert coordinator.devices["SERIAL"]["mode"] == "adjusting"
    assert coordinator.pusher.report_requests == 0


@pytest.mark.asyncio
async def test_unconfirmed_command_rolls_back_after_report_and_rest(
    monkeypatch,
) -> None:
    import custom_components.u_by_moen.coordinator as coordinator_module

    monkeypatch.setattr(coordinator_module, "COMMAND_CONFIRM_TIMEOUT", 0.001)
    monkeypatch.setattr(coordinator_module, "REPORT_CONFIRM_TIMEOUT", 0.001)
    coordinator = make_coordinator({"serial_number": "SERIAL", "mode": "off"})

    with pytest.raises(MoenCommandError, match="did not confirm"):
        await coordinator.async_set_power("SERIAL", True)

    assert coordinator.pusher.report_requests == 1
    assert coordinator.devices["SERIAL"]["mode"] == "off"
    assert coordinator._push_waiters == {}
