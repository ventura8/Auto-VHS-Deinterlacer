"""Regression tests for the per-file coverage gate."""

import importlib.util
import sys
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / ".github" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def _load_enforce_module():
    """Load the coverage gate script as a module for direct testing."""
    script_path = SCRIPTS_DIR / "enforce_per_file_coverage.py"
    spec = importlib.util.spec_from_file_location("enforce_per_file_coverage", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_report(tmp_path: Path, entries: list[tuple[str, float]]) -> Path:
    """Build a two-source-root Cobertura report backed by real files on disk.

    ``entries`` are repo-relative paths; those under ``modules/`` are stored the
    way coverage.py writes them, i.e. relative to the longest matching root.
    """
    classes = []
    for repo_relative, line_rate in entries:
        target = tmp_path / repo_relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("", encoding="utf-8")
        stored = repo_relative.removeprefix("modules/")
        classes.append(f'<class filename="{stored}" line-rate="{line_rate}" branch-rate="1.0" />')

    xml_path = tmp_path / "coverage.xml"
    xml_path.write_text(
        f"""<coverage line-rate="0.9" branch-rate="0.8">
  <sources>
    <source>{tmp_path}</source>
    <source>{tmp_path / "modules"}</source>
  </sources>
  <packages><package name="."><classes>{"".join(classes)}</classes></package></packages>
</coverage>""",
        encoding="utf-8",
    )
    return xml_path


def _run_gate(module, xml_path: Path, threshold: float = 90.0) -> tuple[int, str]:
    output = StringIO()
    with redirect_stdout(output):
        exit_code = module.enforce_per_file_coverage(xml_path, threshold)
    return exit_code, output.getvalue()


def test_gate_reports_source_relative_paths_as_repo_relative(tmp_path):
    """Filenames stored against the modules/ source root regain their prefix."""
    xml_path = _write_report(
        tmp_path,
        [
            ("auto_deinterlancer.py", 0.95),
            ("modules/__init__.py", 1.0),
            ("modules/core/config.py", 0.94),
        ],
    )

    exit_code, rendered = _run_gate(_load_enforce_module(), xml_path)

    assert exit_code == 0
    assert "modules/core/config.py: 94.00% (PASS)" in rendered
    assert "modules/__init__.py: 100.00% (PASS)" in rendered
    assert "  - config.py" not in rendered


def test_gate_fails_on_new_subpackage_below_threshold(tmp_path):
    """A subpackage the old prefix allowlist did not know about is still gated."""
    xml_path = _write_report(
        tmp_path,
        [
            ("modules/core/config.py", 0.94),
            ("modules/gpu/accel.py", 0.10),
        ],
    )

    exit_code, rendered = _run_gate(_load_enforce_module(), xml_path)

    assert exit_code == 1
    assert "modules/gpu/accel.py: 10.00%" in rendered


def test_gate_fails_loudly_on_unclassifiable_entry(tmp_path):
    """Entries that resolve outside the measured sources fail instead of being skipped."""
    xml_path = _write_report(tmp_path, [("modules/core/config.py", 0.94)])
    xml_path.write_text(
        xml_path.read_text(encoding="utf-8").replace(
            "</classes>",
            '<class filename="/elsewhere/stray.py" line-rate="0.0" branch-rate="0.0" /></classes>',
        ),
        encoding="utf-8",
    )

    exit_code, rendered = _run_gate(_load_enforce_module(), xml_path)

    assert exit_code == 1
    assert "Unclassified entries" in rendered
    assert "stray.py" in rendered
