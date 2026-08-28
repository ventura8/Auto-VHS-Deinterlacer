"""End-to-End installer execution tests verifying clean environment installation."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest


def _resolve_venv_python(root: Path) -> Path:
    """Find and verify python binary inside venv directory."""
    venv_dir = root / ".venv" if (root / ".venv").exists() else root / ".VENV"
    assert venv_dir.exists(), "Virtual environment directory must exist"

    python_bin = venv_dir / "bin" / "python"
    if not python_bin.exists():
        python_bin = venv_dir / "Scripts" / "python.exe"
    assert python_bin.exists(), "Python binary must exist inside venv"
    return python_bin


def _require_installer_prerequisites():
    """Skip when required host media tools are unavailable."""
    if not all(shutil.which(tool) for tool in ("ffmpeg", "ffprobe", "git")):
        pytest.skip("installer prerequisites are not available on the test runner")


def _assert_executable(path: Path):
    """Assert a file exists and is executable."""
    assert path.exists()
    assert os.access(path, os.X_OK)


@pytest.mark.skipif(os.name == "nt", reason="install.sh requires a POSIX shell")
@pytest.mark.e2e
@pytest.mark.real_deps
def test_install_sh_execution_and_artifacts(tmp_path):
    """Verify that install.sh runs cleanly and produces all expected artifacts."""
    root = Path(__file__).resolve().parents[2]
    _require_installer_prerequisites()

    isolated_root = tmp_path / "checkout"
    ignored = shutil.ignore_patterns(".git", ".venv", ".VENV", "__pycache__", "*.pyc")
    shutil.copytree(root, isolated_root, ignore=ignored)
    install_script = isolated_root / "install.sh"
    start_script = isolated_root / "start.sh"

    _assert_executable(install_script)
    # Exercise base setup with VapourSynth while avoiding optional ML packages.
    # The plugin build and static FFmpeg download are covered elsewhere.
    install_env = {
        **os.environ,
        "AVD_SKIP_ML_HEAVY": "1",
        "AVD_SKIP_VS_PLUGINS": "1",
        "AVD_SKIP_FFMPEG": "1",
    }
    for variable in ("VIRTUAL_ENV", "PYTHONHOME", "PYTHONPATH"):
        install_env.pop(variable, None)
    subprocess.run([str(install_script)], cwd=isolated_root, check=True, timeout=600, env=install_env)

    python_bin = _resolve_venv_python(isolated_root)
    out = subprocess.check_output([str(python_bin), "--version"]).decode().strip()
    assert "3.12" in out
    _assert_executable(start_script)
    site_packages = Path(subprocess.check_output([str(python_bin), "-c", "import site; print(site.getsitepackages()[0])"]).decode().strip())
    vspipe_name = "vspipe.exe" if os.name == "nt" else "vspipe"
    _assert_executable(site_packages / "vapoursynth" / vspipe_name)
    subprocess.run([str(python_bin), "-c", "import havsfunc, mvsfunc"], check=True, timeout=30)
