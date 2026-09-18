"""Integration-test isolation: never let a test write into the repository root."""

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _isolate_working_directory(monkeypatch, tmp_path):
    """Run every test from a throwaway folder so relative paths cannot leak files."""
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def stub_source_digest():
    """Replace the sampled content digest for tests whose input file does not exist.

    The pipeline tests that mock ``Path.stat`` on a made-up input never create
    the file, and the source identity now also reads samples of its content.
    Request this fixture from those tests only; every workspace and resume test
    keeps hashing real bytes.
    """
    with patch("modules.runtime.workspace._sample_digest", return_value="stub-digest"):
        yield
