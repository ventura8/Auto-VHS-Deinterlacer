"""Unit tests for runtime helper behavior in core and runtime modules."""

import hashlib
import importlib
import io
import os
import re
import runpy
import shutil
import signal
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, mock_open, patch

import pytest


def test_auto_deinterlancer_main_keyboard_interrupt_path():
    """Cover the __main__ KeyboardInterrupt exit guard."""
    with patch("modules.runtime.pipeline.main", side_effect=KeyboardInterrupt):
        with patch("sys.exit") as mock_exit:
            runpy.run_module("auto_deinterlancer", run_name="__main__")
            mock_exit.assert_called_once_with(0)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("C:/repo/.venv/Scripts/vspipe.exe", False),
        ("C:/Python312/python.exe", True),
        ("C:/repo/.venv/Scripts/vspipe-script.py", True),
        ("C:/repo/.venv/vs/vspipe.exe", False),
        ("/repo/.venv/bin/vspipe", False),
    ],
)
def test_is_python_vspipe_launcher_detection(path, expected):
    """Detect Python-launcher vspipe wrappers separately from native binaries."""
    utils = importlib.import_module("modules.core.utils")

    assert utils.is_python_vspipe_launcher(path) is expected


def test_portable_site_packages_path_uses_venv_python_version(tmp_path):
    """Use the actual selected venv's Unix site-packages directory."""
    vspipe = importlib.import_module("modules.runtime.vspipe")
    venv_root = tmp_path / ".venv"
    site_packages = venv_root / "lib" / "python3.12" / "site-packages"
    site_packages.mkdir(parents=True)

    get_site_packages_path = getattr(vspipe, "_get_portable_site_packages_path")
    with patch("sys.platform", "linux"):
        assert get_site_packages_path(str(venv_root)) == site_packages.as_posix()


@pytest.mark.parametrize(
    ("plugin_name", "alias_prefix"),
    [
        ("LSMASHSource.dll", "libvslsmashsource"),
        ("RemoveGrainVS.dll", "libremovegrain"),
    ],
)
@pytest.mark.parametrize("extension", [".so", ".dylib"])
def test_find_plugin_candidate_supports_unix_aliases(tmp_path, plugin_name, alias_prefix, extension):
    """Resolve Unix plugin aliases for LSMASHSource and RemoveGrain."""
    vspipe = importlib.import_module("modules.runtime.vspipe")
    candidate = tmp_path / f"{alias_prefix}{extension}"
    candidate.touch()

    find_plugin_candidate = getattr(vspipe, "_find_plugin_candidate")
    assert find_plugin_candidate(str(tmp_path), plugin_name) == candidate.as_posix()


def test_log_helpers_swallow_flush_and_logger_errors():
    """Cover inner and outer exception guards in logging helpers."""
    utils = importlib.import_module("modules.core.utils")

    bad_handler = MagicMock()
    bad_handler.flush.side_effect = ValueError("flush failed")

    logger_with_bad_flush = MagicMock()
    logger_with_bad_flush.handlers = [bad_handler]

    with patch("modules.core.utils.logger", logger_with_bad_flush):
        utils.log_debug("d")
        utils.log_info("i")
        utils.log_error("e")

    logger_raising = MagicMock()
    logger_raising.handlers = []
    logger_raising.debug.side_effect = ValueError("debug fail")
    logger_raising.info.side_effect = ValueError("info fail")
    logger_raising.error.side_effect = ValueError("error fail")

    with patch("modules.core.utils.logger", logger_raising):
        utils.log_debug("d2")
        utils.log_info("i2")
        utils.log_error("e2")


def test_path_setup_helpers_and_environment_fallbacks():
    """Cover path helper branches and setup_environment exception handling."""
    utils = importlib.import_module("modules.core.utils")

    def exists_for_venv(path):
        p = str(path).replace("\\", "/")
        if p.endswith("/.venv/Scripts"):
            return False
        if p.endswith("/.venv/bin"):
            return True
        return False

    with patch("modules.core.utils.os.path.exists", side_effect=exists_for_venv):
        with patch.dict("modules.core.utils.os.environ", {"PATH": "C:/Windows"}, clear=True):
            getattr(utils, "_add_venv_to_path")("/repo/.venv")
            assert "/repo/.venv/bin" in utils.os.environ["PATH"].replace("\\", "/")

    def exists_for_vs(path):
        p = str(path).replace("\\", "/")
        if p.endswith("/venv/vs"):
            return True
        if p.endswith("/venv/vs/plugins"):
            return False
        if p.endswith("/venv/vs/vs-plugins"):
            return True
        return False

    with patch("modules.core.utils.os.path.exists", side_effect=exists_for_vs):
        with patch("modules.core.utils.platform.system", return_value="Windows"):
            with patch("modules.core.utils.os.add_dll_directory", side_effect=OSError("dll"), create=True):
                with patch.dict("modules.core.utils.os.environ", {"PATH": "C:/Windows"}, clear=True):
                    getattr(utils, "_setup_vapoursynth_portable")("/venv")
                    assert "VAPOURSYNTH_PLUGIN_PATH" in utils.os.environ
                    assert "vs-plugins" in utils.os.environ["VAPOURSYNTH_PLUGIN_PATH"].replace("\\", "/")

    with patch("modules.core.utils.platform.system", return_value="Windows"):
        with patch("modules.core.utils.os.add_dll_directory", return_value="handle", create=True):
            with patch.object(utils, "DLL_DIRECTORY_HANDLES", []):
                getattr(utils, "_add_windows_dll_directory")("C:/vs")
                assert utils.DLL_DIRECTORY_HANDLES == ["handle"]

    with patch("modules.core.utils.get_project_root", side_effect=OSError("root")):
        utils.setup_environment()


def test_cleanup_progress_branches():
    """Cover cleanup exception path and progress clamping."""
    utils = importlib.import_module("modules.core.utils")

    work_dir = MagicMock()
    temp_file = MagicMock()
    temp_file.is_file.return_value = True
    temp_file.name = "demo_temp_script.vpy"
    temp_file.unlink.side_effect = OSError("locked")
    work_dir.glob.return_value = [temp_file]

    utils.cleanup_temp_files(work_dir, "demo")
    assert temp_file.unlink.called

    with patch("sys.stderr") as mock_stderr:
        utils.update_progress(-5.0, "ClampLow")
        utils.update_progress(150.0, "ClampHigh")
        writes = "".join(call.args[0] for call in mock_stderr.write.call_args_list)
        assert "  0.0%" in writes
        assert "100.0%" in writes


def _fake_vapoursynth(*, nnedi3cl, eedi3cl):
    """Build a stand-in vapoursynth module whose core has the requested plugins."""
    core = SimpleNamespace()
    if nnedi3cl:
        core.nnedi3cl = SimpleNamespace(NNEDI3CL=lambda *a, **k: None)
    if eedi3cl:
        core.eedi3m = SimpleNamespace(EEDI3CL=lambda *a, **k: None)
    elif nnedi3cl:
        core.eedi3m = SimpleNamespace()
    return SimpleNamespace(core=core)


def test_vapoursynth_has_opencl_qtgmc_true_when_plugins_present():
    """Probe returns True only when both nnedi3cl and eedi3m.EEDI3CL exist."""
    utils = importlib.import_module("modules.core.utils")
    utils.vapoursynth_has_opencl_qtgmc.cache_clear()
    fake = _fake_vapoursynth(nnedi3cl=True, eedi3cl=True)
    with patch.dict("sys.modules", {"vapoursynth": fake}):
        assert utils.vapoursynth_has_opencl_qtgmc() is True
    utils.vapoursynth_has_opencl_qtgmc.cache_clear()


def test_vapoursynth_has_opencl_qtgmc_uses_nnedi3cl_for_default_mode():
    """The default NNEDI3 mode works without the unused EEDI3CL plugin."""
    utils = importlib.import_module("modules.core.utils")
    partials = (
        _fake_vapoursynth(nnedi3cl=True, eedi3cl=False),
        SimpleNamespace(
            core=SimpleNamespace(nnedi3cl=SimpleNamespace(NNEDI3CL=lambda *a, **k: None), eedi3m=SimpleNamespace(EEDI3CL=None))
        ),
        None,
    )
    for partial in partials:
        utils.vapoursynth_has_opencl_qtgmc.cache_clear()
        with patch.dict("sys.modules", {"vapoursynth": partial}):
            assert utils.vapoursynth_has_opencl_qtgmc(require_eedi3cl=False) is (partial is not None)
            assert utils.vapoursynth_has_opencl_qtgmc(require_eedi3cl=True) is False
    utils.vapoursynth_has_opencl_qtgmc.cache_clear()


def test_vapoursynth_has_opencl_qtgmc_runtime_probe_rejects_crashing_plugin():
    """A present legacy plugin is disabled if an isolated render probe fails."""
    utils = importlib.import_module("modules.core.utils")
    fake = _fake_vapoursynth(nnedi3cl=True, eedi3cl=False)
    utils.vapoursynth_has_opencl_qtgmc.cache_clear()
    with patch.dict("sys.modules", {"vapoursynth": fake}):
        with patch.object(utils, "_vapoursynth_nnedi3cl_renders_frame", return_value=False):
            assert utils.vapoursynth_has_opencl_qtgmc(require_eedi3cl=False, verify_runtime=True) is False
    utils.vapoursynth_has_opencl_qtgmc.cache_clear()


def test_vapoursynth_nnedi3cl_renders_frame_reports_probe_outcome():
    """The out-of-process NNEDI3CL probe maps return codes and errors to a bool."""
    utils = importlib.import_module("modules.core.utils")
    renders_frame = getattr(utils, "_vapoursynth_nnedi3cl_renders_frame")

    with patch("modules.core.utils.subprocess.run", return_value=SimpleNamespace(returncode=0)):
        assert renders_frame() is True

    with patch("modules.core.utils.subprocess.run", return_value=SimpleNamespace(returncode=1)):
        assert renders_frame() is False

    with patch("modules.core.utils.subprocess.run", side_effect=OSError("python missing")):
        assert renders_frame() is False


def test_get_gpu_name_parses_nvidia_output():
    """GPU helper should return the parsed NVIDIA model name."""
    utils = importlib.import_module("modules.core.utils")

    with patch("subprocess.check_output", return_value=b"GPU 0: NVIDIA GeForce RTX 4090 (UUID: test)"):
        assert utils.get_gpu_name() == "NVIDIA GeForce RTX 4090"


def test_get_nvidia_gpu_info_and_fallback_share_parser():
    """Cover shared NVIDIA GPU parsing and its fallback behavior."""
    utils = importlib.import_module("modules.core.utils")

    with patch(
        "subprocess.check_output",
        return_value=b"GPU 0: NVIDIA GeForce RTX 4090 (UUID: test)\nGPU 1: NVIDIA GeForce RTX 4060 (UUID: test2)",
    ):
        assert utils.get_nvidia_gpu_info() == (0, "NVIDIA GeForce RTX 4090")
        assert utils.get_gpu_name() == "NVIDIA GeForce RTX 4090"

    with patch("subprocess.check_output", side_effect=FileNotFoundError()):
        assert utils.get_nvidia_gpu_info() == (None, None)
        assert utils.get_gpu_name() == "Generic / Not Detected"


def test_has_av1_nvenc_capability_requires_successful_encode():
    """AV1 NVENC is enabled only after FFmpeg completes a probe encode."""
    utils = importlib.import_module("modules.core.utils")

    with patch("modules.core.utils.subprocess.run", return_value=SimpleNamespace(returncode=0)) as mock_run:
        assert utils.has_av1_nvenc_capability() is True

    command = mock_run.call_args.args[0]
    assert {"color=c=black:s=256x256:r=1", "av1_nvenc"}.issubset(command)

    failure_runs = {
        "nonzero return code": {"return_value": SimpleNamespace(returncode=1)},
        "ffmpeg missing": {"side_effect": OSError("ffmpeg unavailable")},
    }
    for label, run_kwargs in failure_runs.items():
        with patch("modules.core.utils.subprocess.run", **run_kwargs):
            assert utils.has_av1_nvenc_capability() is False, label


def test_auto_deinterlancer_export_public_symbols_guards(ad):
    """Cover explicit export guard rails in the wrapper entrypoint."""
    export_public_symbols = getattr(ad, "_export_public_symbols")
    exported_by = getattr(ad, "_EXPORTED_BY")

    with pytest.raises(RuntimeError, match="must define __all__"):
        export_public_symbols(SimpleNamespace(__name__="missing_all"))

    bad_all_module = SimpleNamespace(__name__="bad_all", __all__="not-a-sequence")
    with pytest.raises(TypeError, match="must be a list, tuple, or set"):
        export_public_symbols(bad_all_module)

    missing_symbol_module = SimpleNamespace(__name__="missing_symbol", __all__=["ghost"])
    with pytest.raises(RuntimeError, match="contains missing symbol"):
        export_public_symbols(missing_symbol_module)

    exported_backup = dict(exported_by)
    try:
        exported_by.clear()
        exported_by["dup"] = "first.module"
        duplicate_module = SimpleNamespace(__name__="second.module", __all__=["dup"], dup=1)
        with pytest.raises(RuntimeError, match="Duplicate exported symbol"):
            export_public_symbols(duplicate_module)
    finally:
        exported_by.clear()
        exported_by.update(exported_backup)


def test_cleanup_on_exit_signal_terminates_and_kills_process():
    """Signal shutdown should terminate lingering children and raise SystemExit."""
    utils = importlib.import_module("modules.core.utils")

    proc = MagicMock()
    proc.pid = 123
    proc.poll.side_effect = [None, None]

    active_backup = list(utils.ACTIVE_PROCS)
    try:
        utils.ACTIVE_PROCS[:] = [proc]
        with patch("modules.core.utils.time.sleep"):
            with patch("modules.core.utils.sys.exit", side_effect=SystemExit(1)):
                with pytest.raises(SystemExit):
                    utils.cleanup_on_exit(signal.SIGTERM)
        assert proc.terminate.called
        assert proc.kill.called
    finally:
        utils.ACTIVE_PROCS[:] = active_backup


def test_parse_ffmpeg_time_rollover_paths():
    """Timestamp rounding should roll over ms, seconds, and minutes correctly."""
    utils = importlib.import_module("modules.core.utils")

    sec, ts, speed = utils.parse_ffmpeg_time("frame=1 time=00:59:59.9996 speed=1x")
    assert sec == pytest.approx(3599.9996)
    assert ts == "01:00:00,000"
    assert speed == "1.00x"


def test_get_cpu_name_falls_back_to_platform_processor():
    """CPU lookup should return platform fallback when registry access fails."""
    utils = importlib.import_module("modules.core.utils")

    fake_winreg = MagicMock()
    fake_winreg.OpenKey.side_effect = OSError("registry denied")

    with patch("modules.core.utils.winreg", fake_winreg):
        with patch("modules.core.utils._get_linux_cpu_name", return_value=None):
            with patch("modules.core.utils._get_macos_cpu_name", return_value=None):
                with patch("modules.core.utils.platform.processor", return_value="Fallback CPU"):
                    assert utils.get_cpu_name() == "Fallback CPU"


def _assert_file_safe_from_unquoted_batch_injection(path):
    content = path.read_text(encoding="utf-8")
    assert "%*" not in content
    assert '"%~1"' in content


def test_start_bat_script_quotes_arguments():
    """Verify that start.bat (if generated) and install.ps1 do not execute unquoted %* command injection."""
    utils = importlib.import_module("modules.core.utils")
    root = Path(utils.get_project_root())

    start_bat = root / "start.bat"
    if start_bat.exists():
        _assert_file_safe_from_unquoted_batch_injection(start_bat)
    _assert_file_safe_from_unquoted_batch_injection(root / "install.ps1")


def test_install_ps1_verifies_download_hashes():
    """Verify that install.ps1 contains SHA256 integrity verification for downloads."""
    utils = importlib.import_module("modules.core.utils")
    root = Path(utils.get_project_root())
    install_ps1_content = (root / "install.ps1").read_text(encoding="utf-8")

    assert "$sevenZipExpectedSha256" in install_ps1_content
    assert "$havsfuncExpectedSha256" in install_ps1_content
    assert "$mvsfuncCommit" in install_ps1_content
    assert "$ffmpegExpectedSha256" in install_ps1_content


# Trusted SHA-256 digests of the evermeet.cx FFmpeg 9.0.2 archives pinned by
# install.sh. Update these together with FF_VER when the bundled FFmpeg is bumped.
FFMPEG_ZIP_SHA256 = "4acc0be580f9b2788029eb7bd4d645ff87968911b0a62aeeb3940d42d54558d5"
FFPROBE_ZIP_SHA256 = "24a9c968cd4da72d99c7245e914b921815835eb6dff01d99868031aebaf1d439"
# Fixed BtbN FFmpeg-Builds release tag and the trusted SHA-256 digests of its
# 9.0.2 Linux archives pinned by install_linux_ffmpeg(), keyed by the BtbN
# platform suffix. Update these together with FF_TAG/FF_VER on a bump.
LINUX_FFMPEG_TAG = "autobuild-2026-09-19-13-11"
LINUX_TAR_SHA256 = {
    "linux64": "c67af56466837059601a1abd22109b7b771eeea137c9ff4b1db0bde66192dbc6",
    "linuxarm64": "100182dfa879b37caa327b00f7020f04e2dd95c282e171efb92bff262259d463",
}


def _read_install_sh() -> str:
    utils = importlib.import_module("modules.core.utils")
    return (Path(utils.get_project_root()) / "install.sh").read_text(encoding="utf-8")


def _extract_shell_function(script: str, name: str) -> str:
    """Return the full text of a top-level ``name() { ... }`` function from a shell script."""
    match = re.search(rf"^{re.escape(name)}\(\) \{{\n.*?^\}}$", script, re.MULTILINE | re.DOTALL)
    assert match, f"{name}() not found in install.sh"
    return match.group(0)


def test_install_sh_verifies_download_hashes():
    """Verify that install.sh pins the trusted SHA-256 hashes for every downloaded archive.

    The macOS FFmpeg builds from evermeet.cx ship without a checksum file, so the
    hashes must be pinned in the script itself (parity with install.ps1). The
    exact values are asserted so that neither a mistyped nor a placeholder digest
    can pass this test.
    """
    install_sh_content = _read_install_sh()
    darwin_fn = _extract_shell_function(install_sh_content, "install_darwin_ffmpeg")
    linux_fn = _extract_shell_function(install_sh_content, "install_linux_ffmpeg")

    # (haystack, fragment, must_be_present) triples; each platform branch of the
    # installer must route through its verified function, which must pin the
    # digest in the script, hash the download, and delete-on-mismatch. The Darwin
    # branch must never fall back to an unguarded extractall(). The Linux function
    # must pin a fixed release tag rather than BtbN's moving "latest" (whose
    # checksums.sha256 lives in the same release and so proves nothing).
    rules = (
        (install_sh_content, "HAVSFUNC_EXPECTED_SHA256", True),
        (install_sh_content, f'FFMPEG_ZIP_EXPECTED_SHA256="{FFMPEG_ZIP_SHA256}"', True),
        (install_sh_content, f'FFPROBE_ZIP_EXPECTED_SHA256="{FFPROBE_ZIP_SHA256}"', True),
        (install_sh_content, 'install_darwin_ffmpeg "$FF_TMP"', True),
        (install_sh_content, 'install_linux_ffmpeg "$FF_TMP" "$(uname -m)"', True),
        (install_sh_content, "extractall", False),
        (darwin_fn, 'sha256_of "$_ff_tmp/${tool}.zip"', True),
        (darwin_fn, 'rm -f "$_ff_tmp/${tool}.zip"', True),
        (linux_fn, f'FF_EXPECT="{LINUX_TAR_SHA256["linux64"]}"', True),
        (linux_fn, f'FF_EXPECT="{LINUX_TAR_SHA256["linuxarm64"]}"', True),
        (linux_fn, f'FF_TAG="{LINUX_FFMPEG_TAG}"', True),
        (linux_fn, 'sha256_of "$_ff_tmp/ff.tar.xz"', True),
        (linux_fn, 'rm -f "$_ff_tmp/ff.tar.xz"', True),
        (linux_fn, "releases/download/latest", False),
        (linux_fn, "checksums.sha256", False),
    )
    violations = [fragment for haystack, fragment, present in rules if (fragment in haystack) != present]
    assert violations == []


def _make_zip(path: Path, members: dict[str, bytes]) -> str:
    """Write a zip with the given members and return its SHA-256 hex digest."""
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pin_for(tmp_path: Path, tool: str, members: dict[str, bytes]) -> str:
    """Digest of a probe archive identical to what the stubbed curl will serve for ``tool``."""
    return _make_zip(tmp_path / f"probe_{tool}.zip", members)


def _run_darwin_ffmpeg_install(tmp_path: Path, archives: dict[str, dict[str, bytes]], *, pin_overrides: dict[str, str]):
    """Execute install.sh's install_darwin_ffmpeg() against fixture archives with a stubbed curl.

    ``pin_overrides`` maps the pinned-digest variable name to the digest the fixture
    should be verified against; this substitutes the trusted values in the extracted
    function text only (install.sh itself is never modified).
    """
    script = _read_install_sh()
    fn_text = _extract_shell_function(script, "install_darwin_ffmpeg")
    for var, digest in pin_overrides.items():
        fn_text, count = re.subn(rf'{var}="[0-9a-f]{{64}}"', f'{var}="{digest}"', fn_text)
        assert count == 1, var
    sha_fn = _extract_shell_function(script, "sha256_of")

    mirror = tmp_path / "mirror"
    mirror.mkdir()
    for tool, members in archives.items():
        _make_zip(mirror / f"{tool}-9.0.2.zip", members)
    # curl -fsSL <url> -o <dest>  ->  copy the mirrored archive for that URL.
    # A shell function shadows the real curl whatever PATH the bash in use
    # builds for itself. A stub executable prepended to PATH did not survive
    # Git's bin\bash.exe wrapper, which puts Git's own bin directories first
    # and let the real curl download the real archives.
    curl_fn = (
        "curl() {\n"
        '    url="${@: -3:1}"; dest="${@: -1}"\n'
        f'    src="{_bash_path(mirror)}/$(basename "$url")"\n'
        '    [ -f "$src" ] || return 22\n'
        '    cp "$src" "$dest"\n'
        "}\n"
    )

    venv_dir = tmp_path / "venv"
    (venv_dir / "bin").mkdir(parents=True)
    ff_tmp = tmp_path / "ff_tmp"
    ff_tmp.mkdir()
    driver = (
        "set -u\n"
        f"{curl_fn}{sha_fn}\n{fn_text}\n"
        f'VENV_PYTHON="{_bash_path(sys.executable)}"\nVENV_DIR="{_bash_path(venv_dir)}"\nFF_OK=0\n'
        f'install_darwin_ffmpeg "{_bash_path(ff_tmp)}"\n'
        'echo "FF_OK=$FF_OK"\n'
    )
    result = subprocess.run([POSIX_BASH, "-c", driver], capture_output=True, text=True, check=False)
    return result, venv_dir / "bin", ff_tmp


def _installed_names(bin_dir: Path) -> set[str]:
    return {p.name for p in bin_dir.iterdir()}


_GIT_BASH_CANDIDATES = (
    r"C:\Program Files\Git\usr\bin\bash.exe",
    r"C:\Program Files\Git\bin\bash.exe",
)


def _is_posix_bash(candidate) -> bool:
    """Return whether a path is a usable POSIX bash.

    Windows ships a ``bash.exe`` in System32 that only launches WSL, so that one
    is rejected; Git for Windows provides a genuine MSYS2 bash instead.
    """
    if not candidate:
        return False
    resolved = Path(candidate)
    if resolved.stem.lower() != "bash" or "system32" in str(resolved).lower():
        return False
    return resolved.exists()


def _resolve_posix_bash() -> str | None:
    """Locate a real POSIX bash, including Git Bash on Windows.

    On Windows the MSYS2 bash under ``Git\\usr\\bin`` is preferred over
    whatever ``bash`` is first on PATH: GitHub's Windows runners put ``Git\\bin``
    there, and its ``bash.exe`` is a wrapper that prepends Git's own bin
    directories to PATH before running the same MSYS2 bash, so anything a
    test prepends to PATH is shadowed by Git's tools.
    """
    candidates = []
    if sys.platform == "win32":
        candidates.extend(_GIT_BASH_CANDIDATES)
    candidates.append(shutil.which("bash"))
    return next((str(Path(candidate)) for candidate in candidates if _is_posix_bash(candidate)), None)


POSIX_BASH = _resolve_posix_bash()


def _bash_path(path) -> str:
    """Render a path for a bash command line.

    Git Bash needs ``/c/Users/...`` rather than ``C:\\Users\\...``: a Windows
    path embedded in a double-quoted shell string would have its backslashes
    eaten as escape characters.
    """
    text = str(path)
    if sys.platform != "win32":
        return text
    drive, rest = os.path.splitdrive(text)
    rest = rest.replace("\\", "/")
    if drive:
        return f"/{drive[0].lower()}{rest}"
    return rest


# install.sh is the POSIX installer. It runs wherever a real POSIX bash exists,
# including Git Bash on Windows; only a host without one skips these.
_needs_bash = pytest.mark.skipif(
    POSIX_BASH is None,
    reason="requires a POSIX bash (no Git Bash or system bash found)",
)

_FFMPEG_STUB = b"#!/bin/sh\necho ffmpeg\n"
_FFPROBE_STUB = b"#!/bin/sh\necho ffprobe\n"


@_needs_bash
def test_install_darwin_ffmpeg_accepts_matching_archives(tmp_path):
    """Genuine archives (digest matches the pin) are extracted and installed."""
    archives = {"ffmpeg": {"ffmpeg": _FFMPEG_STUB}, "ffprobe": {"ffprobe": _FFPROBE_STUB}}
    pins = {
        "FFMPEG_ZIP_EXPECTED_SHA256": _pin_for(tmp_path, "ffmpeg", archives["ffmpeg"]),
        "FFPROBE_ZIP_EXPECTED_SHA256": _pin_for(tmp_path, "ffprobe", archives["ffprobe"]),
    }

    result, bin_dir, _ = _run_darwin_ffmpeg_install(tmp_path, archives, pin_overrides=pins)

    assert (result.returncode, "FF_OK=1" in result.stdout) == (0, True), result.stderr
    installed = {name: ((bin_dir / name).read_bytes(), os.access(bin_dir / name, os.X_OK)) for name in _installed_names(bin_dir)}
    assert installed == {"ffmpeg": (_FFMPEG_STUB, True), "ffprobe": (_FFPROBE_STUB, True)}


@_needs_bash
def test_install_darwin_ffmpeg_rejects_digest_mismatch(tmp_path):
    """A tampered archive is deleted, reported, and nothing is installed."""
    archives = {"ffmpeg": {"ffmpeg": b"ok"}, "ffprobe": {"ffprobe": b"evil"}}
    pins = {
        "FFMPEG_ZIP_EXPECTED_SHA256": _pin_for(tmp_path, "ffmpeg", archives["ffmpeg"]),
        "FFPROBE_ZIP_EXPECTED_SHA256": "0" * 64,  # will not match the served ffprobe archive
    }

    result, bin_dir, ff_tmp = _run_darwin_ffmpeg_install(tmp_path, archives, pin_overrides=pins)

    expected_messages = ("ffprobe-9.0.2.zip SHA-256 mismatch", "Refusing to install the unverified archive")
    assert [msg for msg in expected_messages if msg not in result.stdout] == []
    # FF_OK stays 0, the rejected archive is deleted, and nothing reaches the venv.
    assert ("FF_OK=0" in result.stdout, (ff_tmp / "ffprobe.zip").exists(), _installed_names(bin_dir)) == (True, False, set())


@_needs_bash
@pytest.mark.parametrize(
    "ffprobe_members",
    [
        pytest.param({"ffprobe": b"ok", "extra": b"payload"}, id="unexpected-extra-member"),
        pytest.param({"ffmpeg": b"ok"}, id="wrong-member-name"),
        pytest.param({"../ffprobe": b"escape"}, id="zip-slip-parent-path"),
        pytest.param({"/tmp/ffprobe": b"escape"}, id="zip-slip-absolute-path"),
    ],
)
def test_install_darwin_ffmpeg_rejects_bad_archive_members(tmp_path, ffprobe_members):
    """An archive whose digest matches but whose members are unexpected or escaping is rejected."""
    archives = {"ffmpeg": {"ffmpeg": b"ok"}, "ffprobe": ffprobe_members}
    pins = {
        "FFMPEG_ZIP_EXPECTED_SHA256": _pin_for(tmp_path, "ffmpeg", archives["ffmpeg"]),
        "FFPROBE_ZIP_EXPECTED_SHA256": _pin_for(tmp_path, "ffprobe", ffprobe_members),
    }

    result, bin_dir, ff_tmp = _run_darwin_ffmpeg_install(tmp_path, archives, pin_overrides=pins)

    assert ("FF_OK=0" in result.stdout, "unexpected archive contents for ffprobe" in result.stderr) == (True, True)
    # Nothing may be written to the venv, the temp dir, or (zip-slip) its parent.
    leaked = [p for p in (bin_dir / "ffprobe", ff_tmp / "ffprobe", tmp_path / "ffprobe") if p.exists()]
    assert leaked == []


@_needs_bash
def test_install_darwin_ffmpeg_handles_download_failure(tmp_path):
    """A failed download leaves FF_OK=0 and installs nothing."""
    archives = {"ffmpeg": {"ffmpeg": b"ok"}}  # ffprobe is not mirrored -> curl exits 22
    pins = {
        "FFMPEG_ZIP_EXPECTED_SHA256": _pin_for(tmp_path, "ffmpeg", archives["ffmpeg"]),
        "FFPROBE_ZIP_EXPECTED_SHA256": "0" * 64,
    }

    result, bin_dir, _ = _run_darwin_ffmpeg_install(tmp_path, archives, pin_overrides=pins)

    assert ("FF_OK=0" in result.stdout, _installed_names(bin_dir)) == (True, set())


def _make_tar_xz(path: Path, members: dict[str, bytes]) -> str:
    """Write a .tar.xz with the given members and return its SHA-256 hex digest."""
    with tarfile.open(path, "w:xz") as tf:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o755
            tf.addfile(info, io.BytesIO(data))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _linux_tar_members(plat: str) -> dict[str, bytes]:
    """Members of a BtbN-style archive for ``plat``: ``ffmpeg-n9.0.2-<plat>-gpl-9.0/bin/{ffmpeg,ffprobe}``."""
    root = f"ffmpeg-n9.0.2-{plat}-gpl-9.0/bin"
    return {f"{root}/ffmpeg": _FFMPEG_STUB, f"{root}/ffprobe": _FFPROBE_STUB}


_LINUX_TAR_MEMBERS = _linux_tar_members("linux64")


def _override_linux_pin(fn_text: str, machine: str, digest: str) -> str:
    """Substitute the pinned digest for ``machine``'s BtbN platform in the extracted function text."""
    plat = {"x86_64": "linux64", "aarch64": "linuxarm64"}[machine]
    fn_text, count = re.subn(rf'(FF_PLAT="{plat}"\n\s+FF_EXPECT=)"[0-9a-f]{{64}}"', rf'\1"{digest}"', fn_text)
    assert count == 1, plat
    return fn_text


def _run_linux_ffmpeg_install(tmp_path: Path, machine: str, members: dict[str, bytes] | None, *, pin_override: str | None):
    """Execute install.sh's install_linux_ffmpeg() against a fixture archive with a stubbed curl.

    ``members`` is the archive served for every URL (``None`` -> curl fails with
    22). ``pin_override`` replaces the pinned digest for ``machine``'s platform in
    the extracted function text only (install.sh itself is never modified).
    Returns ``(result, bin_dir, ff_tmp, curl_log)`` where ``curl_log`` lists each
    URL the stub was asked for.
    """
    script = _read_install_sh()
    fn_text = _extract_shell_function(script, "install_linux_ffmpeg")
    if pin_override is not None:
        fn_text = _override_linux_pin(fn_text, machine, pin_override)
    sha_fn = _extract_shell_function(script, "sha256_of")

    mirror = tmp_path / "mirror"
    mirror.mkdir()
    if members is not None:
        _make_tar_xz(mirror / "served.tar.xz", members)
    curl_log = tmp_path / "curl.log"
    curl_fn = (
        "curl() {\n"
        '    url="${@: -3:1}"; dest="${@: -1}"\n'
        f'    echo "$url" >> "{_bash_path(curl_log)}"\n'
        f'    src="{_bash_path(mirror)}/served.tar.xz"\n'
        '    [ -f "$src" ] || return 22\n'
        '    cp "$src" "$dest"\n'
        "}\n"
    )

    venv_dir = tmp_path / "venv"
    (venv_dir / "bin").mkdir(parents=True)
    ff_tmp = tmp_path / "ff_tmp"
    ff_tmp.mkdir()
    driver = (
        "set -u\n"
        f"{curl_fn}{sha_fn}\n{fn_text}\n"
        f'VENV_DIR="{_bash_path(venv_dir)}"\nFF_OK=0\n'
        f'install_linux_ffmpeg "{_bash_path(ff_tmp)}" "{machine}"\n'
        'echo "FF_OK=$FF_OK"\n'
    )
    result = subprocess.run([POSIX_BASH, "-c", driver], capture_output=True, text=True, check=False)
    urls = curl_log.read_text().split() if curl_log.exists() else []
    return result, venv_dir / "bin", ff_tmp, urls


@_needs_bash
@pytest.mark.parametrize(
    ("machine", "plat"),
    [pytest.param("x86_64", "linux64", id="linux64"), pytest.param("aarch64", "linuxarm64", id="linuxarm64")],
)
def test_install_linux_ffmpeg_accepts_matching_archive(tmp_path, machine, plat):
    """A genuine archive (digest matches the pin for this arch) is fetched from the fixed tag and installed."""
    members = _linux_tar_members(plat)
    pin = _make_tar_xz(tmp_path / "probe.tar.xz", members)

    result, bin_dir, _, urls = _run_linux_ffmpeg_install(tmp_path, machine, members, pin_override=pin)

    assert (result.returncode, "FF_OK=1" in result.stdout) == (0, True), result.stderr
    installed = {name: ((bin_dir / name).read_bytes(), os.access(bin_dir / name, os.X_OK)) for name in _installed_names(bin_dir)}
    assert installed == {"ffmpeg": (_FFMPEG_STUB, True), "ffprobe": (_FFPROBE_STUB, True)}
    # Exactly one download, from a fixed autobuild tag, for this arch's asset.
    expected_url = f"https://github.com/BtbN/FFmpeg-Builds/releases/download/{LINUX_FFMPEG_TAG}/ffmpeg-n9.0.2-{plat}-gpl-9.0.tar.xz"
    assert urls == [expected_url]


@_needs_bash
def test_install_linux_ffmpeg_rejects_digest_mismatch(tmp_path):
    """A tampered archive is deleted on every attempt, retried three times, and nothing is installed."""
    tampered = {**_LINUX_TAR_MEMBERS, "ffmpeg-n9.0.2-linux64-gpl-9.0/bin/ffmpeg": b"#!/bin/sh\necho evil\n"}

    # pin_override=None keeps install.sh's real pinned digest, which the fixture cannot match.
    result, bin_dir, ff_tmp, urls = _run_linux_ffmpeg_install(tmp_path, "x86_64", tampered, pin_override=None)

    assert result.stdout.count("FFmpeg archive SHA-256 mismatch") == 3, result.stdout
    assert result.stdout.count("Deleted corrupt archive") == 3
    assert (len(urls), "FF_OK=0" in result.stdout, (ff_tmp / "ff.tar.xz").exists(), _installed_names(bin_dir)) == (3, True, False, set())
    # The tampered payload never got extracted into the temp dir either.
    assert not any(ff_tmp.rglob("ffmpeg"))


@_needs_bash
def test_install_linux_ffmpeg_handles_download_failure(tmp_path):
    """A failed download is retried three times, leaves FF_OK=0 and installs nothing."""
    result, bin_dir, _, urls = _run_linux_ffmpeg_install(tmp_path, "x86_64", None, pin_override=None)

    assert (len(urls), "FF_OK=0" in result.stdout, _installed_names(bin_dir)) == (3, True, set())


@_needs_bash
def test_install_linux_ffmpeg_skips_unsupported_arch(tmp_path):
    """An architecture without a pinned build is reported and never downloaded."""
    result, bin_dir, _, urls = _run_linux_ffmpeg_install(tmp_path, "riscv64", _LINUX_TAR_MEMBERS, pin_override=None)

    assert ("No prebuilt FFmpeg" in result.stdout, "FF_OK=0" in result.stdout, urls, _installed_names(bin_dir)) == (True, True, [], set())


def test_get_linux_cpu_name_parses_cpuinfo():
    """Verify _get_linux_cpu_name extracts model name correctly."""
    utils = importlib.import_module("modules.core.utils")
    fake_cpuinfo = "processor\t: 0\nmodel name\t: AMD Ryzen 9 5950X 16-Core Processor\nflags\t: fpu\n"
    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=fake_cpuinfo)):
            val = getattr(utils, "_get_linux_cpu_name")()
            assert val == "AMD Ryzen 9 5950X 16-Core Processor"


def test_get_macos_cpu_name_parses_sysctl():
    """Verify _get_macos_cpu_name queries sysctl."""
    utils = importlib.import_module("modules.core.utils")
    with patch("subprocess.check_output", return_value=b"Apple M2 Max\n"):
        val = getattr(utils, "_get_macos_cpu_name")()
        assert val == "Apple M2 Max"


def test_cleanup_temp_files_only_removes_legacy_artifacts_for_stem(tmp_path):
    """Legacy per-source leftovers go; unrelated user files and other stems stay."""
    utils = importlib.import_module("modules.core.utils")
    legacy = [
        "tape_temp_script.vpy",
        "tape_intermediate.mov",
        "tape.mpg.ffindex",
        "tape.mpg.lwi",
        "tape_deinterlaced_prores_part.mov",
    ]
    keep = ["tape.mpg", "my_template.vpy", "other_temp_script.vpy", "tape_deinterlaced_prores.mov"]
    for name in legacy + keep:
        (tmp_path / name).write_bytes(b"x")

    utils.cleanup_temp_files(tmp_path, "tape")

    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(keep)


def test_cleanup_legacy_cache_dir_removes_only_our_folder(tmp_path):
    """The pre-1.2 system-temp index cache is removed; siblings are untouched."""
    utils = importlib.import_module("modules.core.utils")
    ours = tmp_path / "auto-vhs-deinterlancer" / "ffms2"
    ours.mkdir(parents=True)
    (ours / "abc.ffindex").write_bytes(b"x")
    other = tmp_path / "someone-else"
    other.mkdir()

    with patch("modules.core.utils.tempfile.gettempdir", return_value=str(tmp_path)):
        utils.cleanup_legacy_cache_dir()
        utils.cleanup_legacy_cache_dir()

    assert not (tmp_path / "auto-vhs-deinterlancer").exists()
    assert other.is_dir()


def test_get_available_ffmpeg_encoders_parses_listing():
    """The encoder listing is parsed into bare encoder names."""
    utils = importlib.import_module("modules.core.utils")
    utils.get_available_ffmpeg_encoders.cache_clear()
    listing = (
        b"Encoders:\n"
        b" V..... = Video\n"
        b" ------\n"
        b" V....D libaom-av1           libaom AV1 (codec av1)\n"
        b" V..... libsvtav1            SVT-AV1 encoder (codec av1)\n"
        b" A....D aac                  AAC (Advanced Audio Coding)\n"
    )

    with patch("modules.core.utils.subprocess.check_output", return_value=listing):
        names = utils.get_available_ffmpeg_encoders()

    utils.get_available_ffmpeg_encoders.cache_clear()
    assert {"libaom-av1", "libsvtav1", "aac"} <= names
    assert "Encoders:" not in names


def test_get_available_ffmpeg_encoders_returns_empty_on_failure():
    """A missing or failing FFmpeg yields an empty set instead of raising."""
    utils = importlib.import_module("modules.core.utils")
    utils.get_available_ffmpeg_encoders.cache_clear()

    with patch("modules.core.utils.subprocess.check_output", side_effect=OSError("no ffmpeg")):
        assert utils.get_available_ffmpeg_encoders() == frozenset()

    utils.get_available_ffmpeg_encoders.cache_clear()
