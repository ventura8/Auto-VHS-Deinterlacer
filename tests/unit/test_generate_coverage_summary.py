"""Regression tests for the coverage summary generator."""

import importlib.util
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path


def _load_generate_coverage_summary_module():
    """Load the coverage summary script as a module for direct testing."""
    script_path = Path(__file__).resolve().parents[2] / ".github" / "scripts" / "generate_coverage_summary.py"
    spec = importlib.util.spec_from_file_location("generate_coverage_summary", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_generate_summary_preserves_distinct_relative_paths(tmp_path):
    """Rows should keep normalized relative paths instead of collapsing to basenames."""
    xml_path = tmp_path / "coverage.xml"
    xml_path.write_text(
        """
<coverage line-rate="0.9" branch-rate="0.8">
  <packages>
    <package name="core">
      <classes>
        <class filename="modules/core/__init__.py" line-rate="1.0" branch-rate="1.0" complexity="1" />
      </classes>
    </package>
    <package name="runtime">
      <classes>
        <class filename="modules/runtime/__init__.py" line-rate="0.5" branch-rate="0.25" complexity="2" />
      </classes>
    </package>
  </packages>
</coverage>
""".strip(),
        encoding="utf-8",
    )

    module = _load_generate_coverage_summary_module()
    output = StringIO()

    with redirect_stdout(output):
        module.generate_summary(str(xml_path))

    rendered = output.getvalue()
    assert "modules/core/__init__.py" in rendered
    assert "modules/runtime/__init__.py" in rendered
    assert "| __init__.py |" not in rendered
