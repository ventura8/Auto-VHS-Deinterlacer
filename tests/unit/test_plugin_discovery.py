"""Tests for versioned VapourSynth plugin discovery."""

import importlib

import pytest


@pytest.mark.parametrize("library_name", ("libtestplugin.so.12.34", "testplugin.so.12.34"))
def test_find_plugin_in_dirs_supports_multi_component_shared_library_versions(tmp_path, library_name):
    """Find versioned shared libraries without limiting the version suffix."""
    vspipe = importlib.import_module("modules.runtime.vspipe")
    candidate = tmp_path / library_name
    candidate.touch()

    find_plugin = getattr(vspipe, "_find_plugin_in_dirs")
    assert find_plugin([str(tmp_path)], "TestPlugin.dll") == candidate.as_posix()
