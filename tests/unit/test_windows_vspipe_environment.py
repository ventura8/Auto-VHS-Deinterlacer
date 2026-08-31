"""Tests for native Windows VSPipe process environment setup."""

import importlib
from unittest.mock import patch


def test_vspipe_environment_omits_pythonhome_on_windows():
    """Native Windows VSPipe must retain its own Python standard library root."""
    utils = importlib.import_module("modules.core.utils")

    with (
        patch("modules.core.utils.os.name", "nt"),
        patch("modules.core.utils.os.path.exists", return_value=True),
        patch("modules.core.utils.get_project_root", return_value="C:/repo"),
        patch("modules.core.utils.resolve_venv_root", return_value="C:/repo/.venv"),
    ):
        environment = utils.get_vspipe_env()

    assert "PYTHONHOME" not in environment
    assert environment["PYTHONPATH"].replace("\\", "/") == "C:/repo/.venv/Lib/site-packages"
