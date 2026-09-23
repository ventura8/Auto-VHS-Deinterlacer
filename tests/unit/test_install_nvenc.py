"""Tests for install.sh's NVENC step.

Each test extracts the real functions from install.sh and drives them under
``set -euo pipefail`` (as the installer runs) with the system tools replaced by
shell functions. Shell functions shadow commands whatever PATH the bash in use
builds for itself, which a stub prepended to PATH does not under Git Bash.
"""

import importlib
import subprocess

import pytest

_HELPERS = importlib.import_module("tests.unit.test_runtime_helpers")
_POSIX_BASH = getattr(_HELPERS, "POSIX_BASH")
_NVENC_FUNCTIONS = (
    "linux_distro_family",
    "nvenc_library_package",
    "nvenc_library_present",
    "install_nvenc_package",
    "report_av1_nvenc",
    "ensure_nvenc_runtime",
)

pytestmark = pytest.mark.skipif(_POSIX_BASH is None, reason="requires a POSIX bash (no Git Bash or system bash found)")

_API_TOO_OLD = (
    "[av1_nvenc] Driver does not support the required nvenc API version. Required: 13.1 Found: 13.0\n"
    "[av1_nvenc] The minimum required Nvidia driver for nvenc is 610.00 or newer\n"
    "[enc:av1_nvenc] Error while opening encoder\n"
)


def _run(stubs: str, call: str) -> subprocess.CompletedProcess:
    """Run ``call`` after the extracted NVENC functions and ``stubs`` are defined."""
    script = getattr(_HELPERS, "_read_install_sh")()
    extract = getattr(_HELPERS, "_extract_shell_function")
    functions = "\n".join(extract(script, name) for name in _NVENC_FUNCTIONS)
    driver = f"set -euo pipefail\n{functions}\n{stubs}\n{call}\n"
    return subprocess.run([_POSIX_BASH, "-c", driver], capture_output=True, text=True, check=False, timeout=60)


def _ffmpeg_stub(output: str, status: int) -> str:
    """Define ``ff`` to print ``output`` on stderr and exit with ``status``."""
    return f"ff() {{ printf '%s' {_quote(output)} >&2; return {status}; }}"


def _quote(text: str) -> str:
    """Single-quote ``text`` for bash."""
    return "'" + text.replace("'", "'\\''") + "'"


@pytest.mark.parametrize(
    ("family", "expected"),
    [
        ("debian", "libnvidia-encode-595"),
        ("fedora", "xorg-x11-drv-nvidia-cuda-libs"),
        ("arch", "nvidia-utils"),
        ("", ""),
    ],
)
def test_nvenc_library_package_matches_the_driver_branch(family, expected):
    """Debian's package is versioned by driver branch, so it must track the driver."""
    result = _run("", f'nvenc_library_package "{family}" "595.91.07"')

    assert (result.returncode, result.stdout.strip()) == (0, expected)


def test_report_av1_nvenc_confirms_a_working_encoder():
    """A probe that encodes a frame means AV1 output runs on the GPU."""
    result = _run(_ffmpeg_stub("", 0), "report_av1_nvenc ff 610.57.04")

    assert result.returncode == 0
    assert result.stdout.startswith("[OK] AV1 NVENC available")


def test_report_av1_nvenc_names_the_driver_ffmpeg_requires():
    """An NVENC API mismatch reports the minimum driver FFmpeg itself names."""
    result = _run(_ffmpeg_stub(_API_TOO_OLD, 1), "report_av1_nvenc ff 595.91.07")

    assert result.returncode == 0
    assert "NVIDIA driver 595.91.07 is too old" in result.stdout
    assert "it needs 610.00 or newer" in result.stdout
    assert "Error while opening encoder" not in result.stdout


def test_report_av1_nvenc_explains_a_gpu_without_av1_encoding():
    """RTX 30 series and older expose NVENC but reject AV1."""
    result = _run(_ffmpeg_stub("[av1_nvenc] No capable devices found\n", 1), "report_av1_nvenc ff 610.57.04")

    assert "no AV1 encoder (AV1 NVENC needs an RTX 40 or 50 series GPU)" in result.stdout
    assert "will use the CPU encoder instead" in result.stdout


def test_report_av1_nvenc_surfaces_an_unrecognised_failure():
    """An unexpected probe failure is reported by its first line, not swallowed."""
    result = _run(_ffmpeg_stub("[av1_nvenc] something odd\nsecond line\n", 1), "report_av1_nvenc ff 610.57.04")

    assert "AV1 NVENC probe failed: [av1_nvenc] something odd" in result.stdout
    assert "second line" not in result.stdout


def test_ensure_nvenc_runtime_without_a_driver_changes_nothing(tmp_path):
    """With no NVIDIA driver the step reports CPU AV1 and never tries to install."""
    empty_path = getattr(_HELPERS, "_bash_path")(tmp_path)
    result = _run(f'PATH="{empty_path}"', "ensure_nvenc_runtime ff")

    assert result.returncode == 0
    assert "No NVIDIA driver found" in result.stdout


def test_ensure_nvenc_runtime_reports_a_driver_with_no_gpu():
    """nvidia-smi answering without a GPU means the driver is not loaded."""
    result = _run("nvidia-smi() { return 9; }", "ensure_nvenc_runtime ff")

    assert result.returncode == 0
    assert "reported no GPU" in result.stdout


_DRIVER_WITHOUT_LIBRARY = (
    "nvidia-smi() { echo 595.91.07; }\n"
    "ldconfig() { :; }\n"
    "linux_distro_family() { echo debian; }\n"
    "id() { echo 1000; }\n"
    'sudo() { "$@"; }\n'
)


def test_ensure_nvenc_runtime_installs_the_missing_library():
    """A driver without libnvidia-encode gets the package matching its branch."""
    stubs = _DRIVER_WITHOUT_LIBRARY + 'apt-get() { echo "apt-get $*" >&2; }\n' + _ffmpeg_stub("", 0)
    result = _run(stubs, "ensure_nvenc_runtime ff")

    assert result.returncode == 0
    assert "apt-get install -y --no-install-recommends libnvidia-encode-595" in result.stderr
    assert "[OK] AV1 NVENC available" in result.stdout


def test_ensure_nvenc_runtime_survives_a_failed_install():
    """A failed package install is reported but never aborts the installer."""
    stubs = _DRIVER_WITHOUT_LIBRARY + "apt-get() { return 100; }\n" + _ffmpeg_stub("[av1_nvenc] No capable devices found\n", 1)
    result = _run(stubs, "ensure_nvenc_runtime ff")

    assert result.returncode == 0
    assert "Could not install libnvidia-encode-595" in result.stdout


def test_ensure_nvenc_runtime_skips_install_when_the_library_is_present():
    """An existing libnvidia-encode.so.1 is left alone."""
    stubs = (
        "nvidia-smi() { echo 610.57.04; }\n"
        "ldconfig() { echo '    libnvidia-encode.so.1 (libc6,x86-64) => /usr/lib/libnvidia-encode.so.1'; }\n"
        'apt-get() { echo "unexpected apt-get $*" >&2; }\n' + _ffmpeg_stub("", 0)
    )
    result = _run(stubs, "ensure_nvenc_runtime ff")

    assert result.returncode == 0
    assert "unexpected apt-get" not in result.stderr
    assert "[OK] AV1 NVENC available" in result.stdout
