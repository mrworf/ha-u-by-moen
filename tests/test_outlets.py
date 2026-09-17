"""Tests for Android outlet type interpretation."""

import pytest

from custom_components.u_by_moen.outlets import (
    outlet_icon_index,
    outlet_label,
    outlet_mdi_icon,
    outlet_name,
)


@pytest.mark.parametrize(
    ("icon_index", "name", "mdi_icon"),
    [
        (0, "Rain Shower", "mdi:shower"),
        (1, "Overhead Shower", "mdi:shower-head"),
        (2, "Angled Shower", "mdi:shower-head"),
        (3, "Hand Shower", "mdi:shower-head"),
        (4, "Left Body Spray", "mdi:spray"),
        (5, "Right Body Spray", "mdi:spray"),
        (6, "Tub Spout", "mdi:bathtub"),
    ],
)
def test_android_outlet_mapping(icon_index, name, mdi_icon) -> None:
    outlet = {"position": 2, "icon_index": icon_index}

    assert outlet_name(outlet) == name
    assert outlet_label(outlet) == f"{name} (Outlet 2)"
    assert outlet_mdi_icon(outlet, "mdi:fallback") == mdi_icon


def test_nonzero_icon_takes_precedence_over_icon_index() -> None:
    outlet = {"position": 1, "icon": 3, "icon_index": 0}

    assert outlet_icon_index(outlet) == 3
    assert outlet_name(outlet) == "Hand Shower"


@pytest.mark.parametrize("icon_index", [7, 99])
def test_unassigned_and_unknown_icons_fall_back_to_position(icon_index) -> None:
    outlet = {"position": 4, "icon_index": icon_index}

    assert outlet_name(outlet) == "Outlet 4"
    assert outlet_label(outlet) == "Outlet 4"
    assert outlet_mdi_icon(outlet, "mdi:fallback") == "mdi:fallback"
