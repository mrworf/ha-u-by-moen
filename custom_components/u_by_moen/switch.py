"""Switch platform for U by Moen."""

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_OUTLETS,
    DOMAIN,
    ICON_OUTLET,
    ICON_SHOWER,
    MODE_OFF,
    MODE_PAUSED_BY_PRESET,
)
from .coordinator import MoenDataUpdateCoordinator
from .outlets import outlet_mdi_icon, outlet_name

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Moen switch entities."""
    coordinator: MoenDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id][
        "coordinator"
    ]
    entities = []
    for serial_number, device_data in coordinator.data.items():
        # Add main shower on/off switch
        entities.append(MoenShowerSwitch(coordinator, serial_number))

        # Add outlet switches
        outlets = device_data.get(ATTR_OUTLETS, [])
        for outlet in outlets:
            position = outlet.get("position")
            if position:
                entities.append(MoenOutletSwitch(coordinator, serial_number, position))

    async_add_entities(entities)


class MoenShowerSwitch(CoordinatorEntity, SwitchEntity):
    """Representation of a Moen shower on/off switch."""

    _attr_icon = ICON_SHOWER

    def __init__(
        self,
        coordinator: MoenDataUpdateCoordinator,
        serial_number: str,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self._serial_number = serial_number
        self._attr_unique_id = f"{serial_number}_power"

    @property
    def device_info(self):
        """Return device information."""
        device_data = self.coordinator.data[self._serial_number]
        return {
            "identifiers": {(DOMAIN, self._serial_number)},
            "name": device_data.get("name", f"Moen Shower {self._serial_number}"),
            "manufacturer": "Moen",
            "model": "U by Moen Shower",
            "sw_version": device_data.get("current_firmware_version"),
        }

    @property
    def name(self) -> str:
        """Return the name of the switch."""
        device_data = self.coordinator.data[self._serial_number]
        device_name = device_data.get("name", f"Shower {self._serial_number}")
        return f"{device_name} Power"

    @property
    def is_on(self) -> bool:
        """Return true if the shower is on."""
        device_data = self.coordinator.data[self._serial_number]
        mode = device_data.get("mode", MODE_OFF)
        # Treat paused-by-preset like off so UI exposes resume option
        return mode not in (MODE_OFF, MODE_PAUSED_BY_PRESET)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the shower on."""
        await self.coordinator.async_set_power(self._serial_number, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the shower off."""
        await self.coordinator.async_set_power(self._serial_number, False)


class MoenOutletSwitch(CoordinatorEntity, SwitchEntity):
    """Representation of a Moen shower outlet switch."""

    def __init__(
        self,
        coordinator: MoenDataUpdateCoordinator,
        serial_number: str,
        outlet_position: int,
    ) -> None:
        """Initialize the outlet switch."""
        super().__init__(coordinator)
        self._serial_number = serial_number
        self._outlet_position = outlet_position
        self._attr_unique_id = f"{serial_number}_outlet_{outlet_position}"

    @property
    def device_info(self):
        """Return device information."""
        device_data = self.coordinator.data[self._serial_number]
        return {
            "identifiers": {(DOMAIN, self._serial_number)},
            "name": device_data.get("name", f"Moen Shower {self._serial_number}"),
            "manufacturer": "Moen",
            "model": "U by Moen Shower",
            "sw_version": device_data.get("current_firmware_version"),
        }

    @property
    def name(self) -> str:
        """Return the name of the outlet switch."""
        device_data = self.coordinator.data[self._serial_number]
        device_name = device_data.get("name", f"Shower {self._serial_number}")

        # Get outlet name from icon index
        outlet = self._get_outlet_data()
        if outlet:
            return f"{device_name} {outlet_name(outlet)}"

        return f"{device_name} Outlet {self._outlet_position}"

    @property
    def icon(self) -> str:
        """Return the icon for this outlet."""
        outlet = self._get_outlet_data()
        if outlet:
            return outlet_mdi_icon(outlet, ICON_OUTLET)
        return ICON_OUTLET

    @property
    def is_on(self) -> bool:
        """Return true if the outlet is active."""
        outlet = self._get_outlet_data()
        if outlet:
            return outlet.get("active", False)
        return False

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the outlet on."""
        device_data = self.coordinator.data[self._serial_number]
        current_mode = device_data.get("mode", MODE_OFF)

        # If shower is off, turn it on with this outlet
        if current_mode == MODE_OFF:
            _LOGGER.debug(
                "Shower is off, turning on with outlet %d", self._outlet_position
            )
            await self.coordinator.async_set_power(self._serial_number, True)
        elif current_mode == MODE_PAUSED_BY_PRESET:
            _LOGGER.debug(
                "Shower paused by preset, resuming before enabling outlet %d",
                self._outlet_position,
            )
            await self.coordinator.async_set_power(self._serial_number, True)

        await self.coordinator.async_set_outlet(
            self._serial_number, self._outlet_position, True
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the outlet off."""
        device_data = self.coordinator.data[self._serial_number]
        outlets = device_data.get(ATTR_OUTLETS, [])

        # Count how many outlets are currently active
        active_outlets = [o for o in outlets if o.get("active", False)]

        # If this is the only active outlet, turn off the entire shower
        if (
            len(active_outlets) == 1
            and active_outlets[0].get("position") == self._outlet_position
        ):
            _LOGGER.debug("This is the only active outlet, turning off entire shower")
            await self.coordinator.async_set_power(self._serial_number, False)
        else:
            # Otherwise, just turn off this outlet (keep others as-is)
            _LOGGER.debug(
                "Multiple outlets active, turning off only outlet %d",
                self._outlet_position,
            )

            await self.coordinator.async_set_outlet(
                self._serial_number, self._outlet_position, False
            )

    def _get_outlet_data(self) -> dict | None:
        """Get the outlet data for this position."""
        device_data = self.coordinator.data[self._serial_number]
        outlets = device_data.get(ATTR_OUTLETS, [])
        for outlet in outlets:
            if outlet.get("position") == self._outlet_position:
                return outlet
        return None
