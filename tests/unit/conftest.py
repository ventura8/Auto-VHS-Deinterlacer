"""Unit-test isolation: never let a test write into the repository root."""

import pytest


@pytest.fixture(autouse=True)
def _isolate_working_directory(monkeypatch, tmp_path):
    """Run every test from a throwaway folder so relative paths cannot leak files."""
    monkeypatch.chdir(tmp_path)
