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


class HomeAssistant:
    """Type-only Home Assistant test stand-in."""


class DataUpdateCoordinator:
    """Minimal coordinator base used by unit tests."""

    def __init__(self, *_args, **_kwargs) -> None:
        self.data = None

    def async_set_updated_data(self, data) -> None:
        self.data = data


class UpdateFailed(Exception):
    """Test stand-in for Home Assistant's update exception."""


core.HomeAssistant = HomeAssistant
update_coordinator.DataUpdateCoordinator = DataUpdateCoordinator
update_coordinator.UpdateFailed = UpdateFailed
sys.modules.setdefault("homeassistant", homeassistant)
sys.modules.setdefault("homeassistant.core", core)
sys.modules.setdefault("homeassistant.helpers", helpers)
sys.modules.setdefault("homeassistant.helpers.update_coordinator", update_coordinator)
