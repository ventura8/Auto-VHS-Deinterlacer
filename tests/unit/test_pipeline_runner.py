"""Tests for the local CI-parity pipeline script."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def _setup_test_files(tmp_path: Path):
    """Populate sample directory structure with valid and ignored files."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Test\n", encoding="utf-8")
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "guide.md").write_text("# Guide\n", encoding="utf-8")

    venv_dir = tmp_path / ".venv"
    venv_dir.mkdir()
    (venv_dir / "ignored.toml").write_text("dummy", encoding="utf-8")
    (venv_dir / "ignored.md").write_text("dummy", encoding="utf-8")


def _assert_discovered_files(output: str):
    """Assert discovered files contain valid project files and exclude ignored ones."""
    for valid_file in ("pyproject.toml", "README.md", "guide.md"):
        assert valid_file in output
    for ignored_file in ("ignored.toml", "ignored.md"):
        assert ignored_file not in output


def _get_git_bash_candidates() -> list[Path]:
    """Return possible Git Bash executable paths on Windows."""
    candidates: list[Path] = []
    git_exe = shutil.which("git")
    if git_exe:
        git_root = Path(git_exe).resolve().parents[1]
        candidates.extend(
            [
                git_root / "bin" / "bash.exe",
                git_root / "usr" / "bin" / "bash.exe",
            ]
        )
    candidates.extend(
        [
            Path(r"C:\Program Files\Git\bin\bash.exe"),
            Path(r"C:\Program Files\Git\usr\bin\bash.exe"),
            Path(r"C:\Program Files (x86)\Git\bin\bash.exe"),
        ]
    )
    return candidates


def _find_windows_bash() -> str | None:
    """Locate functional Git Bash executable on Windows avoiding WSL stub."""
    for path in _get_git_bash_candidates():
        if path.is_file():
            return str(path)
    return None


def _find_bash_executable() -> str | None:
    """Find a functional bash executable across Linux, macOS, and Windows."""
    if sys.platform == "win32":
        return _find_windows_bash()

    bash_path = shutil.which("bash")
    if bash_path and "System32" not in bash_path:
        return bash_path
    return None


def test_pipeline_falls_back_to_filesystem_discovery_without_git_metadata(tmp_path):
    """Docker release contexts without .git still lint TOML and Markdown files."""
    bash_bin = _find_bash_executable()
    if not bash_bin:
        pytest.skip("Functional bash executable not found on this system")

    pipeline_script = Path(__file__).resolve().parents[2] / "run_pipeline_localy.sh"
    _setup_test_files(tmp_path)

    cmd = (
        f"source {pipeline_script.as_posix()} 2>/dev/null || true; "
        "list_repository_files '*.toml'; echo '---'; list_repository_files '*.md'"
    )
    result = subprocess.run(
        [bash_bin, "-c", cmd],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    _assert_discovered_files(result.stdout)
