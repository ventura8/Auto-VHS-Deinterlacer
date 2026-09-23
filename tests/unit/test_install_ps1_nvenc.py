"""Tests for install.ps1's AV1 NVENC probe under the installer's error settings.

install.ps1 runs with $ErrorActionPreference = "Stop". Under PowerShell 7 with
PSNativeCommandUseErrorActionPreference, a native command's non-zero exit then
throws NativeCommandExitException. The probe fails by design on most machines,
so an unguarded probe aborted the whole Windows install. These tests run the
real function in those settings against a stub ffmpeg executable. POSIX only:
the stub is a shell script; install.ps1's Windows behaviour is covered by CI.
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_PWSH = shutil.which("pwsh")

pytestmark = pytest.mark.skipif(
    _PWSH is None or sys.platform == "win32",
    reason="requires pwsh and a POSIX shell for the stub ffmpeg",
)

_INSTALLER_PREFERENCES = "$ErrorActionPreference = 'Stop'; $PSNativeCommandUseErrorActionPreference = $true;"


def _probe_function(tmp_path: Path) -> Path:
    """Extract Get-Av1NvencStatus from install.ps1 into a dot-sourceable file."""
    installer = (Path(__file__).resolve().parents[2] / "install.ps1").read_text(encoding="utf-8")
    match = re.search(r"^function Get-Av1NvencStatus.*?^\}", installer, re.MULTILINE | re.DOTALL)
    assert match, "Get-Av1NvencStatus not found in install.ps1"
    function_file = tmp_path / "nvenc_probe.ps1"
    function_file.write_text(match.group(0) + "\n", encoding="utf-8")
    return function_file


def _stub_ffmpeg(tmp_path: Path, stderr: str, status: int) -> Path:
    """Write an executable that prints ``stderr`` and exits with ``status``."""
    stub = tmp_path / "ffmpeg"
    stub.write_text(f"#!/bin/sh\nprintf '%s\\n' '{stderr}' >&2\nexit {status}\n", encoding="utf-8")
    stub.chmod(0o755)
    return stub


def _run_probe(tmp_path: Path, stderr: str, status: int) -> subprocess.CompletedProcess:
    """Run the probe inside the installer's preferences, then echo them back."""
    function_file = _probe_function(tmp_path)
    stub = _stub_ffmpeg(tmp_path, stderr, status)
    command = (
        f"{_INSTALLER_PREFERENCES} . '{function_file}'; "
        f"Get-Av1NvencStatus '{stub}'; "
        "'EAP=' + $ErrorActionPreference + ' NATIVE=' + $PSNativeCommandUseErrorActionPreference"
    )
    return subprocess.run([_PWSH, "-NoProfile", "-Command", command], capture_output=True, text=True, check=False, timeout=60)


def test_probe_failure_does_not_abort_the_installer(tmp_path):
    """An unavailable encoder is reported instead of terminating the install."""
    result = _run_probe(tmp_path, "[av1_nvenc] No capable devices found", 187)

    assert result.returncode == 0, result.stderr
    assert "NativeCommandExitException" not in result.stderr
    assert "no AV1 encoder (AV1 NVENC needs an RTX 40 or 50 series GPU)" in result.stdout


def test_probe_leaves_the_installer_preferences_untouched(tmp_path):
    """Relaxing the preferences for the probe must not relax the rest of the install."""
    result = _run_probe(tmp_path, "[av1_nvenc] No capable devices found", 187)

    assert "EAP=Stop NATIVE=True" in result.stdout


def test_probe_names_the_driver_ffmpeg_requires(tmp_path):
    """An NVENC API mismatch reports the minimum driver FFmpeg names."""
    stderr = "Driver does not support the required nvenc API version. The minimum required Nvidia driver for nvenc is 610.00 or newer"
    result = _run_probe(tmp_path, stderr, 218)

    assert "it needs 610.00 or newer" in result.stdout


def test_probe_confirms_a_working_encoder(tmp_path):
    """A probe that encodes a frame reports GPU AV1."""
    result = _run_probe(tmp_path, "", 0)

    assert "[OK] AV1 NVENC available" in result.stdout
