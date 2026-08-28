"""Tests for coverage report source-root normalization."""

import importlib.util
from pathlib import Path
from xml.etree.ElementTree import fromstring


def _load_coverage_paths_module():
    """Load the standalone CI helper module from the repository tree."""
    module_path = Path(__file__).parents[2] / ".github" / "scripts" / "coverage_paths.py"
    spec = importlib.util.spec_from_file_location("coverage_paths", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_extract_source_roots_preserves_windows_drive_root_separator():
    """Keep ``C:/`` usable as a root when Cobertura declares it as a source."""
    coverage_paths = _load_coverage_paths_module()
    root = fromstring("<coverage><sources><source>C:/</source></sources></coverage>")

    assert coverage_paths.extract_source_roots(root) == ["C:/"]


def test_extract_source_roots_preserves_posix_root_separator():
    """Keep ``/`` usable as a root when Cobertura declares it as a source."""
    coverage_paths = _load_coverage_paths_module()
    root = fromstring("<coverage><sources><source>/</source></sources></coverage>")

    assert coverage_paths.extract_source_roots(root) == ["/"]
