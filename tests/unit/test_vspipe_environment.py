"""Unit tests for the native VSPipe process environment."""

import importlib
from unittest.mock import patch


def test_get_vspipe_env_populates_portable_paths():
    """Cover portable vspipe env setup including vs-plugins fallback."""
    utils = importlib.import_module("modules.core.utils")

    def exists_side_effect(path):
        normalized = str(path).replace("\\", "/")
        return normalized.endswith(("/.venv", "/.venv/vs", "/.venv/vs/vs-plugins"))

    with patch("modules.core.utils.get_project_root", return_value="/repo"):
        with patch("modules.core.utils.os.path.exists", side_effect=exists_side_effect):
            with patch.dict("modules.core.utils.os.environ", {"PATH": "/usr/bin"}, clear=True):
                environment = utils.get_vspipe_env()

    assert "PYTHONHOME" not in environment
    assert "site-packages" in environment["PYTHONPATH"].replace("\\", "/")
    assert "vs-plugins" in environment["PATH"].replace("\\", "/")


def test_get_vspipe_env_fallback_to_sys_executable_parent():
    """Use the active interpreter parent when the project venv is absent."""
    utils = importlib.import_module("modules.core.utils")

    def exists_side_effect(path):
        return str(path).replace("\\", "/").lower().endswith("/python/vs")

    with patch("modules.core.utils.get_project_root", return_value="C:/repo"):
        with patch("modules.core.utils.os.path.exists", side_effect=exists_side_effect):
            with patch("modules.core.utils.sys.executable", "C:/python/Scripts/python.exe"):
                with patch.dict("modules.core.utils.os.environ", {"PATH": ""}, clear=True):
                    environment = utils.get_vspipe_env()

    assert "PYTHONHOME" not in environment
    assert "site-packages" in environment["PYTHONPATH"].replace("\\", "/")
