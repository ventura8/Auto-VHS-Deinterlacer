"""Regression tests for the coverage summary generator."""

import importlib.util
import sys
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / ".github" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def _load_generate_coverage_summary_module():
    """Load the coverage summary script as a module for direct testing."""
    script_path = SCRIPTS_DIR / "generate_coverage_summary.py"
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


def test_generate_summary_restores_modules_prefix_from_source_roots(tmp_path):
    """Filenames stored relative to the modules/ source root regain their prefix."""
    (tmp_path / "modules" / "core").mkdir(parents=True)
    (tmp_path / "modules" / "core" / "config.py").write_text("", encoding="utf-8")
    (tmp_path / "modules" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "auto_deinterlancer.py").write_text("", encoding="utf-8")

    xml_path = tmp_path / "coverage.xml"
    xml_path.write_text(
        "\n".join(
            [
                '<coverage line-rate="0.9" branch-rate="0.8">',
                "  <sources>",
                f"    <source>{tmp_path}</source>",
                f"    <source>{tmp_path / 'modules'}</source>",
                "  </sources>",
                '  <packages><package name="."><classes>',
                '    <class filename="__init__.py" line-rate="1.0" branch-rate="1.0" />',
                '    <class filename="auto_deinterlancer.py" line-rate="0.9" branch-rate="1.0" />',
                '    <class filename="core/config.py" line-rate="0.94" branch-rate="0.8" />',
                "  </classes></package></packages>",
                "</coverage>",
            ]
        ),
        encoding="utf-8",
    )

    module = _load_generate_coverage_summary_module()
    output = StringIO()

    with redirect_stdout(output):
        module.generate_summary(str(xml_path))

    rendered = output.getvalue()
    assert "| modules/__init__.py |" in rendered
    assert "| modules/core/config.py |" in rendered
    assert "| __init__.py |" not in rendered
    assert "| core/config.py |" not in rendered
