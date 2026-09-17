"""Data update coordinator for U by Moen."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import MoenApi, MoenApiError
from .commands import (
    MoenCommandError,
    outlet_payload,
    power_payload,
    preset_payload,
    temperature_payload,
)
from .const import DOMAIN, UPDATE_INTERVAL
from .presets import (
    MIN_PRESETS,
    PresetConflictError,
    PresetValidationError,
    normalize_positions,
    preset_fingerprint,
    validate_presets,
)
from .pusher import MoenPusherError, MoenPusherTransport
from .state import merge_device_update, merge_rest_snapshot, parse_state_event

_LOGGER = logging.getLogger(__name__)

COMMAND_CONFIRM_TIMEOUT = 5.0
REPORT_CONFIRM_TIMEOUT = 3.0
PRESET_CONFIRM_TIMEOUT = 3.0


@dataclass(frozen=True, slots=True)
class PresetMutationResult:
    """Result of a successful cloud preset mutation."""

    controller_synced: bool


class MoenDataUpdateCoordinator(DataUpdateCoordinator):
    """Manage REST snapshots and live Pusher state."""

    def __init__(
        self, hass: HomeAssistant, api: MoenApi, pusher: MoenPusherTransport
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )
        self.api = api
        self.pusher = pusher
        self.devices: dict[str, dict[str, Any]] = {}
        self._push_fresh: set[str] = set()
        self._push_waiters: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}
        self._command_locks: dict[str, asyncio.Lock] = {}
        self._preset_locks: dict[str, asyncio.Lock] = {}
        self._preset_sync_locks: dict[str, asyncio.Lock] = {}
        self._controller_sync_needed: set[str] = set()

    async def async_start_pusher(self) -> None:
        """Register known devices and start passive live synchronization."""
        for serial_number, details in self.devices.items():
            try:
                await self.api.ensure_mobile_pusher_capability(details)

                async def callback(
                    event: str, payload: Any, serial: str = serial_number
                ) -> None:
                    await self._async_handle_pusher_event(serial, event, payload)

                await self.pusher.register_device(details, callback)
                self._controller_sync_needed.add(serial_number)
            except (MoenApiError, ValueError) as err:
                _LOGGER.warning(
                    "Pusher unavailable for %s; using REST fallback: %s",
                    serial_number,
                    err,
                )
        self.pusher.start()

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        try:
            devices_list = await self.api.get_devices()
            devices_data: dict[str, dict[str, Any]] = {}
            for device in devices_list:
                serial_number = device.get("serial_number")
                if not serial_number:
                    continue
                try:
                    snapshot = await self.api.get_device_details(serial_number)
                    devices_data[serial_number] = merge_rest_snapshot(
                        self.devices.get(serial_number, {}),
                        snapshot,
                        self.pusher.is_healthy(serial_number)
                        and serial_number in self._push_fresh,
                    )
                except MoenApiError as err:
                    _LOGGER.warning(
                        "Failed to refresh device %s: %s", serial_number, err
                    )
                    if serial_number in self.devices:
                        devices_data[serial_number] = self.devices[serial_number]
            self.devices = devices_data
            return devices_data
        except MoenApiError as err:
            raise UpdateFailed(f"Error communicating with U by Moen: {err}") from err

    async def _async_handle_pusher_event(
        self, serial_number: str, event: str, payload: Any
    ) -> None:
        """Apply one private-channel event."""
        if event == "pusher_internal:subscription_succeeded":
            if serial_number in self._controller_sync_needed:
                self.hass.async_create_task(
                    self._async_retry_controller_presets(serial_number),
                    f"U by Moen preset sync {serial_number}",
                )
            return
        if event != "client-state-reported":
            _LOGGER.debug(
                "Ignoring Pusher event %s for device %s", event, serial_number
            )
            return
        event_type, update = parse_state_event(payload)
        if event_type == "boot":
            try:
                await self.pusher.request_report(serial_number)
            except MoenPusherError as err:
                _LOGGER.debug("Could not request report after boot: %s", err)
            return
        if event_type not in ("state_change", "shower_report"):
            _LOGGER.debug(
                "Ignoring Pusher state type %s for device %s", event_type, serial_number
            )
            return
        if serial_number in self.devices and update:
            self.devices[serial_number] = merge_device_update(
                self.devices[serial_number], update
            )
            self._push_fresh.add(serial_number)
            self.async_set_updated_data(self.devices)
            for waiter in tuple(self._push_waiters.get(serial_number, set())):
                waiter.put_nowait(update)

    async def async_replace_presets(
        self,
        serial_number: str,
        baseline_fingerprint: str,
        presets: list[dict[str, Any]],
    ) -> PresetMutationResult:
        """Replace the cloud preset list if the form baseline is still current."""
        lock = self._preset_locks.setdefault(serial_number, asyncio.Lock())
        async with lock:
            current = await self.api.get_device_details(serial_number)
            self._assert_preset_baseline(current, baseline_fingerprint)
            validated = validate_presets(
                presets,
                max_temperature=int(current.get("max_temp", 115)),
                single_outlet_mode=bool(current.get("single_outlet_mode", False)),
            )
            await self.api.update_presets(serial_number, current, validated)
            refreshed = await self._async_refresh_device(serial_number)
            synced = await self._async_sync_controller_presets(
                serial_number, refreshed.get("presets", [])
            )
            return PresetMutationResult(synced)

    async def async_delete_preset(
        self,
        serial_number: str,
        baseline_fingerprint: str,
        position: int,
    ) -> PresetMutationResult:
        """Delete a cloud preset if at least two will remain."""
        lock = self._preset_locks.setdefault(serial_number, asyncio.Lock())
        async with lock:
            current = await self.api.get_device_details(serial_number)
            self._assert_preset_baseline(current, baseline_fingerprint)
            presets = current.get("presets", [])
            if not isinstance(presets, list) or len(presets) <= MIN_PRESETS:
                raise PresetValidationError("minimum_presets")
            if not any(item.get("position") == position for item in presets):
                raise PresetValidationError("preset_missing")
            await self.api.delete_preset(serial_number, position)
            refreshed = await self._async_refresh_device(serial_number)
            synced = await self._async_sync_controller_presets(
                serial_number, refreshed.get("presets", [])
            )
            return PresetMutationResult(synced)

    @staticmethod
    def _assert_preset_baseline(
        device: dict[str, Any], baseline_fingerprint: str
    ) -> None:
        presets = device.get("presets", [])
        if (
            not isinstance(presets, list)
            or preset_fingerprint(presets) != baseline_fingerprint
        ):
            raise PresetConflictError("Preset configuration changed while editing")

    async def _async_refresh_device(self, serial_number: str) -> dict[str, Any]:
        """Refresh one complete device after an authoritative mutation."""
        snapshot = await self.api.get_device_details(serial_number)
        self.devices[serial_number] = snapshot
        self.async_set_updated_data(self.devices)
        return snapshot

    async def _async_retry_controller_presets(self, serial_number: str) -> None:
        """Retry a pending non-control preset synchronization."""
        device = self.devices.get(serial_number)
        if device is None:
            return
        await self._async_sync_controller_presets(
            serial_number, device.get("presets", [])
        )

    async def _async_sync_controller_presets(
        self, serial_number: str, presets: list[dict[str, Any]]
    ) -> bool:
        """Synchronize controller slots 1-2 without activating the shower."""
        core_presets = normalize_positions(presets)[:2]
        if len(core_presets) < MIN_PRESETS:
            self._controller_sync_needed.add(serial_number)
            return False
        lock = self._preset_sync_locks.setdefault(serial_number, asyncio.Lock())
        async with lock:
            waiter: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
            self._push_waiters.setdefault(serial_number, set()).add(waiter)
            try:
                await self.pusher.send_client_event(
                    serial_number,
                    "client-state-desired",
                    {"type": "preset", "data": core_presets},
                )
                await self.pusher.request_report(serial_number)

                def expected(update: dict[str, Any]) -> bool:
                    reported = update.get("presets")
                    return isinstance(reported, list) and preset_fingerprint(
                        normalize_positions(reported)[:2]
                    ) == preset_fingerprint(core_presets)

                if await self._async_wait_for_confirmation(
                    waiter, expected, PRESET_CONFIRM_TIMEOUT
                ):
                    self._controller_sync_needed.discard(serial_number)
                    return True
            except MoenPusherError as err:
                _LOGGER.debug(
                    "Controller preset sync pending for %s: %s", serial_number, err
                )
            finally:
                waiters = self._push_waiters.get(serial_number)
                if waiters is not None:
                    waiters.discard(waiter)
                    if not waiters:
                        self._push_waiters.pop(serial_number, None)
            self._controller_sync_needed.add(serial_number)
            return False

    async def async_set_power(self, serial_number: str, turn_on: bool) -> None:
        """Turn the shower on/resume it, or turn it off."""
        expected = (
            (lambda update: update.get("mode") not in (None, "off"))
            if turn_on
            else (lambda update: update.get("mode") == "off")
        )
        optimistic = {"mode": "adjusting" if turn_on else "off"}
        await self._async_execute_control(
            serial_number,
            power_payload(turn_on),
            optimistic,
            expected,
        )

    async def async_activate_preset(self, serial_number: str, position: int) -> None:
        """Activate one configured preset using the APK's position split."""
        device = self._device(serial_number)
        payload, preset = preset_payload(device.get("presets", []), position)
        optimistic = {
            "active_preset": position,
            **{
                key: preset[key]
                for key in (
                    "target_temperature",
                    "outlets",
                    "timer_enabled",
                    "timer_length",
                )
                if key in preset
            },
        }
        await self._async_execute_control(
            serial_number,
            payload,
            optimistic,
            lambda update: update.get("active_preset") == position,
        )

    async def async_set_temperature(
        self, serial_number: str, temperature: float
    ) -> None:
        """Set the target temperature in whole degrees Fahrenheit."""
        device = self._device(serial_number)
        payload, target = temperature_payload(
            temperature,
            60,
            device.get("max_temp", 115),
        )
        await self._async_execute_control(
            serial_number,
            payload,
            {"target_temperature": target},
            lambda update: update.get("target_temperature") == target,
        )

    async def async_set_outlet(
        self, serial_number: str, position: int, active: bool
    ) -> None:
        """Set one outlet while transmitting the complete ordered outlet state."""
        device = self._device(serial_number)
        payload, outlets = outlet_payload(device.get("outlets", []), position, active)

        def expected(update: dict[str, Any]) -> bool:
            return any(
                outlet.get("position") == position and outlet.get("active") is active
                for outlet in update.get("outlets", [])
                if isinstance(outlet, dict)
            )

        await self._async_execute_control(
            serial_number,
            payload,
            {"outlets": outlets},
            expected,
        )

    def _device(self, serial_number: str) -> dict[str, Any]:
        try:
            return self.devices[serial_number]
        except KeyError as err:
            raise MoenCommandError(f"Unknown shower {serial_number}") from err

    async def _async_execute_control(
        self,
        serial_number: str,
        payload: dict[str, Any],
        optimistic: dict[str, Any],
        expected: Callable[[dict[str, Any]], bool],
    ) -> None:
        """Send, optimistically apply, and then confirm one control command."""
        lock = self._command_locks.setdefault(serial_number, asyncio.Lock())
        async with lock:
            await self._async_execute_control_locked(
                serial_number,
                payload,
                optimistic,
                expected,
            )

    async def _async_execute_control_locked(
        self,
        serial_number: str,
        payload: dict[str, Any],
        optimistic: dict[str, Any],
        expected: Callable[[dict[str, Any]], bool],
    ) -> None:
        """Execute one serialized device command."""
        previous = dict(self._device(serial_number))
        waiter: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._push_waiters.setdefault(serial_number, set()).add(waiter)
        optimistic_applied = False
        try:
            await self.pusher.send_client_event(
                serial_number,
                "client-state-desired",
                payload,
            )
            self.devices[serial_number] = merge_device_update(previous, optimistic)
            optimistic_applied = True
            self.async_set_updated_data(self.devices)

            if await self._async_wait_for_confirmation(
                waiter, expected, COMMAND_CONFIRM_TIMEOUT
            ):
                return
            try:
                await self.pusher.request_report(serial_number)
            except MoenPusherError:
                pass
            else:
                if await self._async_wait_for_confirmation(
                    waiter, expected, REPORT_CONFIRM_TIMEOUT
                ):
                    return

            snapshot = await self.api.get_device_details(serial_number)
            if not expected(snapshot):
                raise MoenCommandError("The shower did not confirm the command")
            self.devices[serial_number] = snapshot
            self.async_set_updated_data(self.devices)
        except MoenCommandError:
            if optimistic_applied:
                self.devices[serial_number] = previous
                self.async_set_updated_data(self.devices)
            raise
        except (MoenApiError, MoenPusherError) as err:
            if optimistic_applied:
                self.devices[serial_number] = previous
                self.async_set_updated_data(self.devices)
            raise MoenCommandError("Could not control the shower") from err
        finally:
            waiters = self._push_waiters.get(serial_number)
            if waiters is not None:
                waiters.discard(waiter)
                if not waiters:
                    self._push_waiters.pop(serial_number, None)

    @staticmethod
    async def _async_wait_for_confirmation(
        waiter: asyncio.Queue[dict[str, Any]],
        expected: Callable[[dict[str, Any]], bool],
        timeout: float,
    ) -> bool:
        deadline = time.monotonic() + timeout
        while (remaining := deadline - time.monotonic()) > 0:
            try:
                update = await asyncio.wait_for(waiter.get(), remaining)
            except asyncio.TimeoutError:
                return False
            if expected(update):
                return True
        return False

    def update_device_from_pusher(
        self, serial_number: str, update_data: dict[str, Any]
    ) -> None:
        """Compatibility helper for directly normalized push data."""
        if serial_number in self.devices:
            self.devices[serial_number] = merge_device_update(
                self.devices[serial_number], update_data
            )
            self._push_fresh.add(serial_number)
            self.async_set_updated_data(self.devices)
