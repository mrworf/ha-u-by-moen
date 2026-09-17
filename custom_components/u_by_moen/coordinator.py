"""Data update coordinator for U by Moen."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import MoenApi, MoenApiError
from .const import DOMAIN, UPDATE_INTERVAL
from .pusher import MoenPusherError, MoenPusherTransport
from .state import merge_device_update, merge_rest_snapshot, parse_state_event

_LOGGER = logging.getLogger(__name__)


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
