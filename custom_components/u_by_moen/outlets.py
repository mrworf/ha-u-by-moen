"""Android-derived outlet names and Home Assistant icons."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class OutletDescriptor:
    """Describe one outlet icon supported by the Moen app."""

    name: str
    mdi_icon: str


OUTLET_DESCRIPTORS = {
    0: OutletDescriptor("Rain Shower", "mdi:shower"),
    1: OutletDescriptor("Overhead Shower", "mdi:shower-head"),
    2: OutletDescriptor("Angled Shower", "mdi:shower-head"),
    3: OutletDescriptor("Hand Shower", "mdi:shower-head"),
    4: OutletDescriptor("Left Body Spray", "mdi:spray"),
    5: OutletDescriptor("Right Body Spray", "mdi:spray"),
    6: OutletDescriptor("Tub Spout", "mdi:bathtub"),
}


def outlet_icon_index(outlet: dict[str, Any]) -> int:
    """Resolve an outlet icon using the Android model's precedence."""
    icon = outlet.get("icon")
    if isinstance(icon, int) and not isinstance(icon, bool) and icon != 0:
        return icon
    icon_index = outlet.get("icon_index", 0)
    if isinstance(icon_index, int) and not isinstance(icon_index, bool):
        return icon_index
    return 0


def outlet_name(outlet: dict[str, Any]) -> str:
    """Return the configured outlet type or a position-based fallback."""
    descriptor = OUTLET_DESCRIPTORS.get(outlet_icon_index(outlet))
    if descriptor is not None:
        return descriptor.name
    position = outlet.get("position")
    return f"Outlet {position}" if position is not None else "Outlet"


def outlet_label(outlet: dict[str, Any]) -> str:
    """Return a preset-form label that retains the physical position."""
    name = outlet_name(outlet)
    position = outlet.get("position")
    if position is None or name == f"Outlet {position}":
        return name
    return f"{name} (Outlet {position})"


def outlet_mdi_icon(outlet: dict[str, Any], fallback: str) -> str:
    """Return the closest Material Design icon for an outlet."""
    descriptor = OUTLET_DESCRIPTORS.get(outlet_icon_index(outlet))
    return descriptor.mdi_icon if descriptor is not None else fallback
