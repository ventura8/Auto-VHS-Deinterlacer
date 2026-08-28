"""Shared pytest fixtures and import-path setup for test modules."""

import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Global Mocks for Windows-specific modules on Linux
# This ensures import statements in the main module don't fail,
# allowing us to test "Windows-like" paths if we choose to.
if sys.platform != "win32":
    if "winreg" not in sys.modules:
        sys.modules["winreg"] = MagicMock()
    if "msvcrt" not in sys.modules:
        sys.modules["msvcrt"] = MagicMock()

# We also want to ensure that ctypes.windll doesn't crash at import time
# if it's accessed at top level (it's not in auto_deinterlancer, but just in case)


@pytest.fixture(autouse=True)
def setup_path():
    """Ensure project root is in sys.path globally for all tests."""
    if PROJECT_ROOT not in sys.path:
        sys.path.insert(0, PROJECT_ROOT)


@pytest.fixture(autouse=True)
def _clear_opencl_qtgmc_probe_cache():
    """Drop cached VapourSynth OpenCL-probe results between tests.

    ``modules.core.utils.vapoursynth_has_opencl_qtgmc`` is ``lru_cache``-wrapped,
    so a probe result (real or mocked) would otherwise leak into later tests.
    """
    probe = importlib.import_module("modules.core.utils").vapoursynth_has_opencl_qtgmc
    probe.cache_clear()
    yield
    probe.cache_clear()


@pytest.fixture
def assume_opencl_qtgmc_available():
    """Pin the VapourSynth OpenCL-plugin probe to "available" for one test.

    Hardware-detection tests assert the Windows/CI baseline where nnedi3cl and
    eedi3m.EEDI3CL are installed, but the bare test venv has neither. Request
    this fixture explicitly from those tests only, so every other test still
    observes the real probe result.
    """
    with patch("modules.core.config.vapoursynth_has_opencl_qtgmc", return_value=True):
        yield


@pytest.fixture
def ad():
    """
    Lazy import fixture for auto_deinterlancer (wrapper) but now primarily used
    if tests still need to reference the entry point logic.
    For module testing, direct imports are preferred.
    """
    # Ensure project root is in sys.path
    if PROJECT_ROOT not in sys.path:
        sys.path.insert(0, PROJECT_ROOT)

    # Remove module from sys.modules if it exists to force a fresh import
    if "auto_deinterlancer" in sys.modules:
        del sys.modules["auto_deinterlancer"]

    return importlib.import_module("auto_deinterlancer")
