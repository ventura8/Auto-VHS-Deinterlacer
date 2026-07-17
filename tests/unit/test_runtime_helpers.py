"""Unit tests for runtime helper behavior in core and runtime modules."""

import importlib
import runpy
import signal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


def test_auto_deinterlancer_main_keyboard_interrupt_path():
    """Cover the __main__ KeyboardInterrupt exit guard."""
    with patch("modules.runtime.pipeline.main", side_effect=KeyboardInterrupt):
        with patch("sys.exit") as mock_exit:
            runpy.run_module("auto_deinterlancer", run_name="__main__")
            mock_exit.assert_called_once_with(0)


def test_get_vspipe_env_populates_portable_paths():
    """Cover portable vspipe env setup including vs-plugins fallback."""
    utils = importlib.import_module("modules.core.utils")

    def exists_side_effect(path):
        p = str(path).replace("\\", "/")
        if p.endswith("/.venv"):
            return True
        if p.endswith("/.venv/vs"):
            return True
        if p.endswith("/.venv/vs/plugins"):
            return False
        if p.endswith("/.venv/vs/vs-plugins"):
            return True
        return False

    with patch("modules.core.utils.get_project_root", return_value="/repo"):
        with patch("modules.core.utils.os.path.exists", side_effect=exists_side_effect):
            with patch.dict("modules.core.utils.os.environ", {"PATH": "/usr/bin"}, clear=True):
                env = utils.get_vspipe_env()

    assert env["PYTHONHOME"].replace("\\", "/").endswith("/.venv/vs")
    assert env["PYTHONPATH"].replace("\\", "/").endswith("/.venv/Lib/site-packages")
    assert "vs-plugins" in env["PATH"].replace("\\", "/")


def test_is_python_vspipe_launcher_detection():
    """Detect Python-launcher vspipe wrappers separately from native binaries."""
    utils = importlib.import_module("modules.core.utils")

    assert utils.is_python_vspipe_launcher("C:/repo/.venv/Scripts/vspipe.exe") is True
    assert utils.is_python_vspipe_launcher("C:/Python312/python.exe") is True
    assert utils.is_python_vspipe_launcher("C:/repo/.venv/Scripts/vspipe-script.py") is True
    assert utils.is_python_vspipe_launcher("C:/repo/.venv/vs/vspipe.exe") is False


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


def test_get_vspipe_env_fallback_to_sys_executable_parent():
    """When .venv is absent, vspipe env should use the active interpreter parent path."""
    utils = importlib.import_module("modules.core.utils")

    def exists_side_effect(path):
        normalized = str(path).replace("\\", "/").lower()
        return normalized.endswith("/python/vs")

    with patch("modules.core.utils.get_project_root", return_value="C:/repo"):
        with patch("modules.core.utils.os.path.exists", side_effect=exists_side_effect):
            with patch("modules.core.utils.sys.executable", "C:/python/Scripts/python.exe"):
                with patch.dict("modules.core.utils.os.environ", {"PATH": ""}, clear=True):
                    env = utils.get_vspipe_env()

    assert env["PYTHONHOME"].replace("\\", "/").endswith("/python/vs")
    assert env["PYTHONPATH"].replace("\\", "/").endswith("/python/Lib/site-packages")


def test_get_cpu_name_falls_back_to_platform_processor():
    """CPU lookup should return platform fallback when registry access fails."""
    utils = importlib.import_module("modules.core.utils")

    fake_winreg = MagicMock()
    fake_winreg.OpenKey.side_effect = OSError("registry denied")

    with patch("modules.core.utils.winreg", fake_winreg):
        with patch("modules.core.utils.platform.processor", return_value="Fallback CPU"):
            assert utils.get_cpu_name() == "Fallback CPU"
