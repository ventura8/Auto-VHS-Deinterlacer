"""Unit tests for runtime helper behavior in core and runtime modules."""

import importlib
import runpy
import signal
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
