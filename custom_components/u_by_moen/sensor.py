"""Sensor platform for U by Moen."""

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_ACTIVE_PRESET,
    ATTR_CURRENT_TEMP,
    ATTR_FIRMWARE,
    ATTR_MODE,
    ATTR_TARGET_TEMP,
    DOMAIN,
    ICON_TEMPERATURE,
)
from .coordinator import MoenDataUpdateCoordinator
from .presets import preset_detail_attributes, preset_inventory, preset_slots

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Moen sensor entities."""
    coordinator: MoenDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id][
        "coordinator"
    ]

    entities = []
    detail_entities: dict[tuple[str, int], MoenPresetDetailSensor] = {}
    for serial_number, device in coordinator.data.items():
        entities.extend(
            [
                MoenModeSensor(coordinator, serial_number),
                MoenCurrentTempSensor(coordinator, serial_number),
                MoenTargetTempSensor(coordinator, serial_number),
                MoenActivePresetSensor(coordinator, serial_number),
                MoenTimeRemainingSensor(coordinator, serial_number),
                MoenFirmwareSensor(coordinator, serial_number),
                MoenPresetCountSensor(coordinator, serial_number),
            ]
        )
        for preset in device.get("presets", []):
            position = preset.get("position")
            if position:
                detail = MoenPresetDetailSensor(
                    coordinator, serial_number, int(position)
                )
                detail_entities[(serial_number, int(position))] = detail
                entities.append(detail)

    async_add_entities(entities)

    @callback
    def reconcile_preset_sensors() -> None:
        """Keep detailed preset sensors aligned with current slots."""
        desired = preset_slots(coordinator.data)
        new_entities = []
        for key in desired - detail_entities.keys():
            entity = MoenPresetDetailSensor(coordinator, key[0], key[1])
            detail_entities[key] = entity
            new_entities.append(entity)
        if new_entities:
            async_add_entities(new_entities)

        registry = er.async_get(hass)
        for key in set(detail_entities) - desired:
            entity = detail_entities.pop(key)
            if entity.hass is not None:
                hass.async_create_task(entity.async_remove())
            entity_id = registry.async_get_entity_id("sensor", DOMAIN, entity.unique_id)
            if entity_id is not None:
                registry.async_remove(entity_id)

    entry.async_on_unload(coordinator.async_add_listener(reconcile_preset_sensors))


class MoenSensorBase(CoordinatorEntity, SensorEntity):
    """Base class for Moen sensors."""

    def __init__(
        self,
        coordinator: MoenDataUpdateCoordinator,
        serial_number: str,
        sensor_type: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._serial_number = serial_number
        self._sensor_type = sensor_type
        self._attr_unique_id = f"{serial_number}_{sensor_type}"

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
    def device_name(self) -> str:
        """Return the device name."""
        device_data = self.coordinator.data[self._serial_number]
        return device_data.get("name", f"Shower {self._serial_number}")


class MoenModeSensor(MoenSensorBase):
    """Sensor for shower mode status."""

    _attr_icon = "mdi:shower"

    def __init__(
        self, coordinator: MoenDataUpdateCoordinator, serial_number: str
    ) -> None:
        """Initialize the mode sensor."""
        super().__init__(coordinator, serial_number, "mode")

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return f"{self.device_name} Mode"

    @property
    def native_value(self) -> str | None:
        """Return the state of the sensor."""
        device_data = self.coordinator.data[self._serial_number]
        return device_data.get(ATTR_MODE)


class MoenCurrentTempSensor(MoenSensorBase):
    """Sensor for current water temperature."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.FAHRENHEIT
    _attr_icon = ICON_TEMPERATURE

    def __init__(
        self, coordinator: MoenDataUpdateCoordinator, serial_number: str
    ) -> None:
        """Initialize the current temperature sensor."""
        super().__init__(coordinator, serial_number, "current_temperature")

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return f"{self.device_name} Current Temperature"

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        device_data = self.coordinator.data[self._serial_number]
        return device_data.get(ATTR_CURRENT_TEMP)


class MoenTargetTempSensor(MoenSensorBase):
    """Sensor for target water temperature."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.FAHRENHEIT
    _attr_icon = ICON_TEMPERATURE

    def __init__(
        self, coordinator: MoenDataUpdateCoordinator, serial_number: str
    ) -> None:
        """Initialize the target temperature sensor."""
        super().__init__(coordinator, serial_number, "target_temperature")

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return f"{self.device_name} Target Temperature"

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        device_data = self.coordinator.data[self._serial_number]
        return device_data.get(ATTR_TARGET_TEMP)


class MoenActivePresetSensor(MoenSensorBase):
    """Sensor for active preset."""

    _attr_icon = "mdi:playlist-star"

    def __init__(
        self, coordinator: MoenDataUpdateCoordinator, serial_number: str
    ) -> None:
        """Initialize the active preset sensor."""
        super().__init__(coordinator, serial_number, "active_preset")

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return f"{self.device_name} Active Preset"

    @property
    def native_value(self) -> str | None:
        """Return the state of the sensor."""
        device_data = self.coordinator.data[self._serial_number]
        preset_position = device_data.get(ATTR_ACTIVE_PRESET, 0)

        if preset_position == 0:
            return "None"

        # Find the preset title
        presets = device_data.get("presets", [])
        for preset in presets:
            if preset.get("position") == preset_position:
                return preset.get("title", f"Preset {preset_position}")

        return f"Preset {preset_position}"


class MoenTimeRemainingSensor(MoenSensorBase):
    """Sensor for time remaining on timer."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_icon = "mdi:timer"

    def __init__(
        self, coordinator: MoenDataUpdateCoordinator, serial_number: str
    ) -> None:
        """Initialize the time remaining sensor."""
        super().__init__(coordinator, serial_number, "time_remaining")

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return f"{self.device_name} Time Remaining"

    @property
    def native_value(self) -> int | None:
        """Return the state of the sensor."""
        device_data = self.coordinator.data[self._serial_number]
        return device_data.get("time_remaining", 0)


class MoenFirmwareSensor(MoenSensorBase):
    """Sensor for firmware version."""

    _attr_icon = "mdi:chip"

    def __init__(
        self, coordinator: MoenDataUpdateCoordinator, serial_number: str
    ) -> None:
        """Initialize the firmware sensor."""
        super().__init__(coordinator, serial_number, "firmware")

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return f"{self.device_name} Firmware"

    @property
    def native_value(self) -> str | None:
        """Return the state of the sensor."""
        device_data = self.coordinator.data[self._serial_number]
        return device_data.get(ATTR_FIRMWARE)


class MoenPresetCountSensor(MoenSensorBase):
    """Sensor exposing preset count and an ordered title summary."""

    _attr_icon = "mdi:playlist-star"

    def __init__(
        self, coordinator: MoenDataUpdateCoordinator, serial_number: str
    ) -> None:
        super().__init__(coordinator, serial_number, "preset_count")

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return f"{self.device_name} Preset Count"

    @property
    def native_value(self) -> int:
        """Return the current number of configured presets."""
        return len(self.coordinator.data[self._serial_number].get("presets", []))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return a compact ordered preset inventory."""
        presets = self.coordinator.data[self._serial_number].get("presets", [])
        return {"presets": preset_inventory(presets)}


class MoenPresetDetailSensor(MoenSensorBase):
    """Sensor exposing all settings for one preset position."""

    _attr_icon = "mdi:playlist-edit"

    def __init__(
        self,
        coordinator: MoenDataUpdateCoordinator,
        serial_number: str,
        position: int,
    ) -> None:
        super().__init__(coordinator, serial_number, f"preset_{position}_details")
        self._position = position

    def _preset(self) -> dict[str, Any] | None:
        for preset in self.coordinator.data[self._serial_number].get("presets", []):
            if preset.get("position") == self._position:
                return preset
        return None

    @property
    def available(self) -> bool:
        """Return whether this preset position still exists."""
        return super().available and self._preset() is not None

    @property
    def name(self) -> str:
        """Return a stable position-oriented entity name."""
        return f"{self.device_name} Preset {self._position} Details"

    @property
    def native_value(self) -> str | None:
        """Return the preset's human-readable title."""
        preset = self._preset()
        return preset.get("title") if preset is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return every configurable preset setting."""
        preset = self._preset()
        if preset is None:
            return {}
        unit = str(self.coordinator.hass.config.units.temperature_unit)
        return preset_detail_attributes(preset, unit)
