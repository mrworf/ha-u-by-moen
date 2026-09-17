"""Test bootstrap that avoids importing Home Assistant for protocol unit tests."""

import sys
from pathlib import Path
from types import ModuleType

PACKAGE_PATH = Path(__file__).parents[1] / "custom_components" / "u_by_moen"

custom_components = ModuleType("custom_components")
custom_components.__path__ = [str(PACKAGE_PATH.parent)]
sys.modules.setdefault("custom_components", custom_components)
package = ModuleType("custom_components.u_by_moen")
package.__path__ = [str(PACKAGE_PATH)]
sys.modules.setdefault("custom_components.u_by_moen", package)

# The protocol/coordinator tests exercise integration logic without installing
# the full Home Assistant runtime.
homeassistant = ModuleType("homeassistant")
homeassistant.__path__ = []
core = ModuleType("homeassistant.core")
helpers = ModuleType("homeassistant.helpers")
helpers.__path__ = []
update_coordinator = ModuleType("homeassistant.helpers.update_coordinator")
config_entries = ModuleType("homeassistant.config_entries")
const = ModuleType("homeassistant.const")
data_entry_flow = ModuleType("homeassistant.data_entry_flow")
aiohttp_client = ModuleType("homeassistant.helpers.aiohttp_client")
config_validation = ModuleType("homeassistant.helpers.config_validation")


class HomeAssistant:
    """Type-only Home Assistant test stand-in."""


def callback(func):
    """Return a Home Assistant callback unchanged."""
    return func


class DataUpdateCoordinator:
    """Minimal coordinator base used by unit tests."""

    def __init__(self, *_args, **_kwargs) -> None:
        self.data = None

    def async_set_updated_data(self, data) -> None:
        self.data = data


class UpdateFailed(Exception):
    """Test stand-in for Home Assistant's update exception."""


class ConfigEntry:
    """Minimal config entry."""

    def __init__(self, entry_id="entry") -> None:
        self.entry_id = entry_id


class FlowBase:
    """Capture flow results as dictionaries."""

    def __init_subclass__(cls, **_kwargs):
        return super().__init_subclass__()

    def async_show_form(self, **kwargs):
        return {"type": "form", **kwargs}

    def async_show_menu(self, **kwargs):
        return {"type": "menu", **kwargs}

    def async_create_entry(self, **kwargs):
        return {"type": "create_entry", **kwargs}


class ConfigFlow(FlowBase):
    """Minimal config flow."""


class OptionsFlow(FlowBase):
    """Minimal options flow."""


def multi_select(options):
    """Return a small multi-select validator."""

    def validate(values):
        if any(value not in options for value in values):
            raise ValueError("invalid selection")
        return values

    return validate


core.HomeAssistant = HomeAssistant
core.callback = callback
homeassistant.config_entries = config_entries
update_coordinator.DataUpdateCoordinator = DataUpdateCoordinator
update_coordinator.UpdateFailed = UpdateFailed
config_entries.ConfigEntry = ConfigEntry
config_entries.ConfigFlow = ConfigFlow
config_entries.OptionsFlow = OptionsFlow
const.CONF_EMAIL = "email"
const.CONF_PASSWORD = "password"
data_entry_flow.FlowResult = dict
aiohttp_client.async_get_clientsession = lambda _hass: None
config_validation.multi_select = multi_select
helpers.config_validation = config_validation
sys.modules.setdefault("homeassistant", homeassistant)
sys.modules.setdefault("homeassistant.core", core)
sys.modules.setdefault("homeassistant.helpers", helpers)
sys.modules.setdefault("homeassistant.helpers.update_coordinator", update_coordinator)
sys.modules.setdefault("homeassistant.config_entries", config_entries)
sys.modules.setdefault("homeassistant.const", const)
sys.modules.setdefault("homeassistant.data_entry_flow", data_entry_flow)
sys.modules.setdefault("homeassistant.helpers.aiohttp_client", aiohttp_client)
sys.modules.setdefault("homeassistant.helpers.config_validation", config_validation)
