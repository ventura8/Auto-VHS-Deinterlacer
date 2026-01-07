import sys
from unittest.mock import MagicMock

# Global Mocks for Windows-specific modules on Linux
# This ensures import statements in the main module don't fail,
# allowing us to test "Windows-like" paths if we choose to.
if sys.platform != 'win32':
    if 'winreg' not in sys.modules:
        sys.modules['winreg'] = MagicMock()
    if 'msvcrt' not in sys.modules:
        sys.modules['msvcrt'] = MagicMock()

# We also want to ensure that ctypes.windll doesn't crash at import time
# if it's accessed at top level (it's not in auto_deinterlancer, but just in case)

import pytest
from pathlib import Path


@pytest.fixture(autouse=True)
def setup_path():
    """Ensure project root is in sys.path globally for all tests."""
    project_root = str(Path(__file__).parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)


@pytest.fixture
def ad():
    """
    Lazy import fixture for auto_deinterlancer (wrapper) but now primarily used
    if tests still need to reference the entry point logic.
    For module testing, direct imports are preferred.
    """
    # Ensure project root is in sys.path
    project_root = str(Path(__file__).parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    # Remove module from sys.modules if it exists to force a fresh import
    if 'auto_deinterlancer' in sys.modules:
        del sys.modules['auto_deinterlancer']

    import auto_deinterlancer
    return auto_deinterlancer
