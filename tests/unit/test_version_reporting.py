"""Unit tests for application version reporting."""

import importlib
import tomllib
from pathlib import Path
from unittest.mock import mock_open, patch

import pytest


def test_get_app_version_reads_pyproject():
    """The banner version must come from pyproject.toml, the single source of truth."""
    utils = importlib.import_module("modules.core.utils")

    version = utils.get_app_version()
    pyproject = Path(utils.SCRIPT_DIR) / "pyproject.toml"
    expected = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]
    assert version == expected


@pytest.mark.parametrize("failure", [OSError("missing"), tomllib.TOMLDecodeError("bad", "", 0)])
def test_get_app_version_returns_unknown_on_unreadable_pyproject(failure):
    """An unreadable or malformed pyproject.toml degrades to 'unknown' instead of raising."""
    utils = importlib.import_module("modules.core.utils")

    with patch("builtins.open", side_effect=failure):
        assert utils.get_app_version() == "unknown"


@pytest.mark.parametrize("project", [{}, "not-a-table", []])
def test_get_app_version_returns_unknown_for_invalid_project_metadata(project):
    """Missing or non-table project metadata degrades to 'unknown'."""
    utils = importlib.import_module("modules.core.utils")

    with patch("modules.core.utils.tomllib.load", return_value={"project": project}):
        with patch("builtins.open", mock_open(read_data=b"")):
            assert utils.get_app_version() == "unknown"


@pytest.mark.parametrize("version", ["", [], {}, 1])
def test_get_app_version_returns_unknown_for_invalid_version_value(version):
    """A missing or non-string project version degrades to 'unknown'."""
    utils = importlib.import_module("modules.core.utils")

    with patch("modules.core.utils.tomllib.load", return_value={"project": {"version": version}}):
        with patch("builtins.open", mock_open(read_data=b"")):
            assert utils.get_app_version() == "unknown"
