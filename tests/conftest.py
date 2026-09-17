"""Test bootstrap that avoids importing Home Assistant for protocol unit tests."""

import sys
from pathlib import Path
from types import ModuleType

PACKAGE_PATH = Path(__file__).parents[1] / "custom_components" / "u_by_moen"

package = ModuleType("custom_components.u_by_moen")
package.__path__ = [str(PACKAGE_PATH)]
sys.modules.setdefault("custom_components.u_by_moen", package)
