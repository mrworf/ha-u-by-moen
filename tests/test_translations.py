"""Tests for integration translation contracts."""

import json
from pathlib import Path

INTEGRATION_DIR = (
    Path(__file__).parents[1] / "custom_components" / "u_by_moen"
)


def test_preset_menu_title_uses_supported_placeholders() -> None:
    """Keep dynamic values in the description, where flow placeholders work."""
    strings = json.loads((INTEGRATION_DIR / "strings.json").read_text())
    english = json.loads(
        (INTEGRATION_DIR / "translations" / "en.json").read_text()
    )

    source_menu = strings["options"]["step"]["preset_menu"]
    translated_menu = english["options"]["step"]["preset_menu"]

    assert source_menu == translated_menu
    assert source_menu["title"] == "Manage presets"
    assert "{" not in source_menu["title"]
    assert source_menu["description"] == (
        "Shower: {device}\n\n"
        "Current presets: {presets}\n\n"
        "Last result: {status}"
    )
