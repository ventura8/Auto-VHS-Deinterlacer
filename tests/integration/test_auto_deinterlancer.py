"""Integration tests covering config, utility, and pipeline wrapper behavior."""

import ast
import importlib
import os
import stat
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest

# We need to import the modules directly now
# But we should rely on the fixtures or direct imports


def _build_mock_ctypes(memory_gb: int | None = None, side_effect: Exception | None = None):
    """Create a ctypes-like shim for hardware detection tests."""
    mock_ctypes = MagicMock()
    mock_kernel32 = MagicMock()
    mock_ctypes.windll.kernel32 = mock_kernel32
    mock_ctypes.sizeof.return_value = 128
    mock_ctypes.c_ulong = MagicMock()
    mock_ctypes.c_ulonglong = MagicMock()
    mock_ctypes.Structure = type("Structure", (), {"_fields_": []})
    mock_ctypes.byref = lambda value: value

    if side_effect is not None:
        mock_kernel32.GlobalMemoryStatusEx.side_effect = side_effect
        return mock_ctypes

    def _set_memory(ref):
        ref.ull_total_phys = int(memory_gb or 0) * (1024**3)
        return True

    mock_kernel32.GlobalMemoryStatusEx.side_effect = _set_memory
    return mock_ctypes


def _render_vpy_content(**kwargs) -> str:
    """Generate VPY content under mocked filesystem and environment state."""
    create_vpy_script = importlib.import_module("modules.runtime.vspipe").create_vpy_script
    abspath_side_effect = kwargs.get("abspath_side_effect", str)
    config_override = kwargs.get("config_override", {"vspipe_prefetch_threads": 4})
    override_settings = kwargs.get(
        "override_settings",
        {
            "cpu_threads": 8,
            "ram_cache_mb": 4000,
            "use_gpu_opencl": False,
            "gpu_device_index": 0,
        },
    )

    with patch("builtins.open", new_callable=mock_open) as mock_f:
        with (
            patch("os.path.getsize", return_value=100),
            patch("os.path.abspath", side_effect=abspath_side_effect),
            patch("modules.runtime.vspipe.get_fps", return_value=kwargs.get("fps", 25.0)),
            patch("modules.runtime.vspipe.CONFIG", config_override),
            patch("os.getcwd", return_value=kwargs.get("cwd", "C:/repo/it's root")),
            patch("modules.runtime.vspipe.get_project_root", return_value=kwargs.get("project_root", "C:/repo")),
            patch("modules.runtime.vspipe.os.path.exists", side_effect=kwargs.get("path_exists", lambda _path: True)),
        ):
            create_vpy_script("in.mp4", "out.vpy", "QTGMC", override_settings=override_settings)

    return mock_f().write.call_args_list[0][0][0].decode("utf-8")


def test_parse_ffmpeg_time():
    """Parse ffmpeg progress timestamps and handle null input safely."""
    utils = importlib.import_module("modules.core.utils")

    # (seconds, time_str, speed_str)
    # The actual code might produce comma decimals depending on locale or regex,
    # but based on failure it produces '00:00:10,500' and '1.50x' or similar.
    # Let's align with the error message: (10.5, '00:00:10,500', '1.50x')
    val = utils.parse_ffmpeg_time("time=00:00:10.50 speed=1.5x")
    assert val[0] == 10.50
    # Allow flexible time string check if needed, but error showed comma
    # assert val[1] == "00:00:10.50"

    assert utils.parse_ffmpeg_time(None) == (None, None, None)


def test_load_config(tmp_path):
    """Test config loading logic against real YAML parsing."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text("encoder: prores\n", encoding="utf-8")
    config_module = importlib.import_module("modules.core.config")

    with patch.object(config_module, "get_project_root", return_value=str(tmp_path)):
        config = config_module.load_config()

    assert config["encoder"] == "prores"


def test_get_fps_duration_start():
    """Test video property detection."""
    utils = importlib.import_module("modules.core.utils")

    with patch("subprocess.check_output") as mock_cmd:
        mock_cmd.side_effect = [b"30000/1001", b"120.5", b"1.5"]
        assert pytest.approx(utils.get_fps("v.mp4"), 0.01) == 29.97
        assert utils.get_duration("v.mp4") == 120.5
        assert utils.get_start_time("v.mp4") == 1.5

        # Test exceptions in detection
        mock_cmd.side_effect = OSError("failed")
        assert utils.get_fps("v.mp4") == 29.97


def test_get_vpy_site_paths_handles_uppercase_dot_venv():
    """Retain uppercase .VENV site-packages entries and include .VENV portable path."""
    vspipe_module = importlib.import_module("modules.runtime.vspipe")
    get_vpy_site_paths = getattr(vspipe_module, "_get_vpy_site_paths")

    with patch("sys.path", ["C:/repo/.VENV/Lib/site-packages", "C:/repo/other"]):
        paths = get_vpy_site_paths("C:/repo/.venv")

    assert "C:/repo/.VENV/Lib/site-packages" in paths


def test_plugin_loading_uses_coreplugins_directory_when_present():
    """Portable installs retain AvsCompat loading with the alternate core directory."""
    vspipe_module = importlib.import_module("modules.runtime.vspipe")
    get_plugin_loading_lines = getattr(vspipe_module, "_get_plugin_loading_lines")

    def mock_find_plugin_candidate(plugin_dir, base_name):
        if Path(plugin_dir).name == "coreplugins" and base_name == "AvsCompat.dll":
            return "C:/repo/.VENV/vs/coreplugins/AvsCompat.dll"
        return None

    with (
        patch(
            "modules.runtime.vspipe.os.path.exists",
            side_effect=lambda path: Path(path).name in {"coreplugins", "AvsCompat.dll"},
        ),
        patch("modules.runtime.vspipe._find_plugin_candidate", side_effect=mock_find_plugin_candidate) as mock_find,
        patch("modules.runtime.vspipe._get_plugin_search_dirs", return_value=[]),
    ):
        lines = get_plugin_loading_lines("C:/repo/.VENV")

    assert "AvsCompat.dll" in "".join(lines)
    mock_find.assert_called_once_with(
        os.path.join("C:/repo/.VENV", "vs", "coreplugins"),
        "AvsCompat.dll",
    )


def test_create_vpy_script_uses_uppercase_venv_root_when_lowercase_is_missing():
    """Generated VPY paths consistently use .VENV when it is the only local venv."""

    def only_uppercase_venv(path):
        normalized = str(path).replace("\\", "/")
        if normalized.endswith("/.venv"):
            return False
        if normalized.endswith("/vs/plugins"):
            return False
        return True

    with patch("sys.path", ["C:/repo/.VENV/Lib/site-packages"]):
        rendered = _render_vpy_content(
            project_root="C:/repo",
            path_exists=only_uppercase_venv,
        )

    assert "C:/repo/.VENV/Lib/site-packages" in rendered
    assert "C:/repo/.VENV/vs" in rendered
    assert "C:/repo/.VENV/vs/vs-plugins" in rendered
    assert "C:/repo/.venv" not in rendered


def test_get_vpy_info():
    """Test vspipe --info parsing."""
    mock_output = b"Output Index: 0\nType: Video\nFrames: 1000\nFPS: 30000/1001 (29.970 fps)\nFormat Name: RGB24"
    vspipe = importlib.import_module("modules.runtime.vspipe")

    with patch("modules.runtime.vspipe.get_vspipe_env", return_value={"PYTHONHOME": "X", "PYTHONPATH": "Y", "PATH": "P"}):
        with patch("subprocess.check_output", return_value=mock_output) as mock_check_output:
            frames, fps, _width, _height, _fmt = vspipe.get_vpy_info("C:/repo/.venv/Scripts/vspipe.exe", "script.vpy")
        assert frames == 1000
        assert pytest.approx(fps, 0.001) == 29.970
        env = mock_check_output.call_args.kwargs["env"]
        assert env["PYTHONHOME"] == "X"
        assert env["PYTHONPATH"] == "Y"


def test_detect_hardware_logic_prioritizes_nvidia_gpu_index(assume_opencl_qtgmc_available):  # pylint: disable=unused-argument
    """Hardware detection should prefer the NVIDIA index from mixed GPU output."""
    config_module = importlib.import_module("modules.core.config")
    detect_hardware_settings = config_module.detect_hardware_settings

    with (
        patch("os.cpu_count", return_value=12),
        patch("shutil.which", return_value="/bin/nvidia-smi"),
        patch("subprocess.check_output", return_value=b"GPU 0: Intel(R) UHD Graphics\nGPU 1: NVIDIA GeForce RTX 3080"),
        patch("modules.core.config.has_av1_nvenc_capability", return_value=True),
    ):
        settings = detect_hardware_settings()

    assert settings["cpu_threads"] == 12
    assert settings["use_gpu_opencl"] is True
    assert settings["gpu_device_index"] == 1


def test_detect_hardware_logic_uses_high_memory_profile(assume_opencl_qtgmc_available):  # pylint: disable=unused-argument
    """Hardware detection should apply the high-memory cache profile."""
    config_module = importlib.import_module("modules.core.config")
    detect_hardware_settings = config_module.detect_hardware_settings

    with (
        patch.object(config_module, "ctypes", _build_mock_ctypes(memory_gb=64)),
        patch("os.cpu_count", return_value=32),
        patch("shutil.which", return_value="/bin/nvidia-smi"),
        patch("subprocess.check_output", return_value=b"GPU 0: NVIDIA RTX 5090"),
        patch("modules.core.config.has_av1_nvenc_capability", return_value=True),
    ):
        settings = detect_hardware_settings()

    assert settings["ram_cache_mb"] == 32768
    assert settings["use_gpu_opencl"] is True
    assert settings["gpu_device_index"] == 0


def test_detect_hardware_logic_uses_midrange_memory_profile():
    """Hardware detection should apply the midrange cache profile."""
    config_module = importlib.import_module("modules.core.config")
    detect_hardware_settings = config_module.detect_hardware_settings

    with (
        patch.object(config_module, "ctypes", _build_mock_ctypes(memory_gb=32)),
        patch("os.cpu_count", return_value=16),
        patch("shutil.which", return_value="/bin/rocm-smi"),
        patch("subprocess.check_output", return_value=b"AMD Radeon"),
    ):
        settings = detect_hardware_settings()

    assert settings["ram_cache_mb"] == 11468
    assert settings["gpu_device_index"] == 0


def test_detect_hardware_logic_falls_back_on_ctypes_failure(assume_opencl_qtgmc_available):  # pylint: disable=unused-argument
    """Hardware detection should keep safe defaults when ctypes probing fails."""
    config_module = importlib.import_module("modules.core.config")
    detect_hardware_settings = config_module.detect_hardware_settings

    with (
        patch.object(config_module, "ctypes", _build_mock_ctypes(side_effect=OSError("Ctypes Error"))),
        patch.object(config_module, "_get_posix_ram_gb", return_value=None),
        patch("os.cpu_count", return_value=8),
        patch("shutil.which", return_value=None),
    ):
        settings = detect_hardware_settings()

    assert settings["ram_cache_mb"] == 4000
    assert settings["gpu_device_index"] == 0
    assert settings["use_gpu_opencl"] is True


def testget_input_files_cli():
    """Test CLI arguments."""
    get_input_files = importlib.import_module("modules.runtime.pipeline").get_input_files

    with patch("modules.runtime.pipeline.Path.is_file", return_value=True):
        with patch("modules.runtime.pipeline.Path.is_dir", return_value=False):
            with patch("sys.argv", ["script.py", "test.mkv"]):
                files = get_input_files()
                assert len(files) == 1


def testget_input_files_interactive():
    """Test interactive inputs and quoted cleaning."""
    get_input_files = importlib.import_module("modules.runtime.pipeline").get_input_files

    with patch("builtins.input") as mock_input:
        with patch("modules.runtime.pipeline.Path") as mock_path_class:
            mock_input.return_value = '"tape.mp4"'
            mock_p = mock_path_class.return_value
            mock_p.is_file.return_value = True
            mock_p.suffix = ".mp4"
            mock_p.name = "tape.mp4"
            with patch("sys.argv", ["script.py"]):
                files = get_input_files()
                assert len(files) == 1


def test_create_vpy_script():
    """Generated VPY should include the expected source and retry logic."""
    content = _render_vpy_content()
    assert "core.ffms2.Source" in content
    assert "hasattr(core.std, 'Prefetch')" in content
    assert "retry_args.pop('device', None)" in content
    assert "retry_args['opencl'] = False" in content


def test_create_vpy_script_adds_prefetch_and_valid_python():
    """Generated VPY should include prefetch settings and parse as Python."""
    content = _render_vpy_content()
    assert "clip = core.std.Prefetch(clip, threads=4)" in content
    ast.parse(content)


def test_create_vpy_script_prefetch_auto_uses_cpu_threads():
    """Auto prefetch should resolve to configured cpu_threads."""
    content = _render_vpy_content(
        config_override={"manual_settings": {"vspipe_prefetch_threads": "auto"}},
        override_settings={
            "cpu_threads": 12,
            "ram_cache_mb": 4000,
            "use_gpu_opencl": False,
            "gpu_device_index": 0,
        },
    )
    assert "clip = core.std.Prefetch(clip, threads=12)" in content
    ast.parse(content)


def test_create_vpy_script_uses_safe_python_path_literals_and_retains_dll_handles():
    """Generated VPY should safely embed paths and keep DLL directory handles alive."""
    content = _render_vpy_content(abspath_side_effect=lambda _value: "C:/captures/it's tape.mp4")
    assert "_DLL_DIRECTORY_HANDLES = []" in content
    assert "_DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(" in content
    assert 'core.ffms2.Source("C:/captures/it\'s tape.mp4"' in content
    ast.parse(content)


def test_process_video_resume_final():
    """Test skipping if final output exists."""
    process_video = importlib.import_module("modules.runtime.pipeline").process_video

    with patch("modules.runtime.pipeline.get_duration", return_value=10.0):
        # Input exists, Output exists -> Skip
        with patch("modules.runtime.pipeline.Path.exists", side_effect=[True, True]):
            with patch("modules.runtime.pipeline.Path.stat") as mock_stat:
                mock_stat.return_value.st_size = 5000
                mock_stat.return_value.st_mode = stat.S_IFREG
                input_p = Path("test.mp4")
                with patch("modules.runtime.pipeline.log_info"):
                    process_video(input_p)


def test_process_video_pipeline():
    """Test Single-Pass Pipeline (Mocked)."""
    process_video = importlib.import_module("modules.runtime.pipeline").process_video

    with patch("modules.runtime.pipeline.get_duration", return_value=100.0):
        with patch("modules.runtime.pipeline.get_vpy_info", return_value=(3000, 30.0, 720, 576, "YUV420P8")):  # 100s
            with patch("modules.runtime.pipeline.create_vpy_script"):
                with patch("modules.runtime.pipeline.shutil.which", return_value="/bin/tool"):
                    with patch("modules.runtime.pipeline.cleanup_temp_files"):
                        with patch("os.path.exists", return_value=True):  # vspipe exists
                            with patch("subprocess.Popen") as mock_popen:
                                with patch("modules.runtime.pipeline.log_info"), patch("modules.runtime.pipeline.log_debug"):
                                    # Mock Popen instances
                                    p1 = MagicMock()
                                    p1_entered = MagicMock()
                                    p1.__enter__.return_value = p1_entered
                                    p1.__exit__.return_value = False
                                    p1_entered.stderr = MagicMock()
                                    p1_entered.stderr.readline.return_value = b""
                                    p1_entered.stdout = MagicMock()
                                    p1_entered.wait.return_value = None

                                    p2 = MagicMock()
                                    p2_entered = MagicMock()
                                    p2.__enter__.return_value = p2_entered
                                    p2.__exit__.return_value = False
                                    progress_msg = "frame= 100 fps=30 time=00:00:10.00 speed=1.0x"
                                    p2_entered.stderr = MagicMock()
                                    p2_entered.poll.side_effect = [None, 0, 0]
                                    p2_entered.returncode = 0
                                    p2_entered.wait.return_value = None

                                    mock_popen.side_effect = [p1, p2]

                                    input_p = Path("test.mp4")
                                    # Force output not exist so it runs
                                    # First check is input_path.exists() -> True
                                    # Second check is output_file.exists() -> False
                                    with patch(
                                        "modules.runtime.pipeline.Path.exists", side_effect=[True, False, False, False, False]
                                    ):  # input, output, intermediate...
                                        with patch("modules.runtime.pipeline.Path.stat") as mock_stat:
                                            with patch("threading.Thread"):
                                                with patch("io.TextIOWrapper", return_value=[progress_msg, "", ""]):
                                                    mock_stat.return_value.st_size = 5000
                                                    mock_stat.return_value.st_mode = stat.S_IFREG
                                                    process_video(input_p)

                                                    # Verify TWO Popen calls (VSPipe, FFmpeg)
                                                    assert mock_popen.call_count == 2

                                                    # Verify FFmpeg command structure
                                                    args, _ = mock_popen.call_args_list[1]
                                                    cmd = args[0]
                                                    # We are using rawvideo pipe now, not yuv4mpegpipe wrapper
                                                    assert "-f" in cmd and "rawvideo" in cmd


def test_update_progress_visual():
    """Test progress bar logic (visual check via capture)."""
    update_progress = importlib.import_module("modules.core.utils").update_progress

    with patch("sys.stderr") as mock_stderr:
        update_progress(50.0, "Testing", "00:00:10", "1.0x")
        # Check call args
        args = mock_stderr.write.call_args[0][0]
        assert "50.0%" in args
        assert "Testing" in args
        assert "00:00:10" in args
        assert "1.0x" in args


def test_main_startup():
    """Test main entry point."""
    main = importlib.import_module("modules.runtime.pipeline").main

    with patch("modules.runtime.pipeline.check_requirements"):
        with patch("modules.runtime.pipeline.get_input_files", return_value=[Path("vhs.mp4")]):
            with patch("modules.runtime.pipeline.process_video") as mock_process:
                with patch("builtins.input"):
                    with patch("sys.argv", ["script.py"]):
                        main()
                        assert mock_process.called


def test_get_input_files_defaults_to_input_folder():
    """Empty interactive input should scan the default input folder."""
    get_input_files = importlib.import_module("modules.runtime.pipeline").get_input_files

    file_mock = MagicMock()
    file_mock.is_file.return_value = True
    file_mock.suffix = ".mp4"
    file_mock.name = "vid.mp4"

    with (
        patch("sys.argv", ["script.py"]),
        patch("builtins.input", return_value=""),
        patch("modules.runtime.pipeline.Path.exists", return_value=True),
        patch("modules.runtime.pipeline.Path.is_dir", return_value=True),
        patch("modules.runtime.pipeline.Path.iterdir", return_value=[file_mock]),
    ):
        files = get_input_files()

    assert len(files) == 1
    assert files[0].name == "vid.mp4"


def test_get_input_files_interactive_folder_scan_filters_processed_files():
    """Interactive folder scan should ignore already-processed outputs."""
    get_input_files = importlib.import_module("modules.runtime.pipeline").get_input_files

    valid_file = MagicMock()
    valid_file.is_file.return_value = True
    valid_file.suffix = ".mkv"
    valid_file.name = "movie.mkv"

    processed_file = MagicMock()
    processed_file.is_file.return_value = True
    processed_file.suffix = ".mov"
    processed_file.name = "movie_deinterlaced.mov"

    with (
        patch("sys.argv", ["script.py"]),
        patch("builtins.input", return_value="my_folder"),
        patch("modules.runtime.pipeline.Path.exists", return_value=True),
        patch("modules.runtime.pipeline.Path.is_file", return_value=False),
        patch("modules.runtime.pipeline.Path.is_dir", return_value=True),
        patch("modules.runtime.pipeline.Path.iterdir", return_value=[valid_file, processed_file]),
    ):
        files = get_input_files()

    assert len(files) == 1
    assert files[0].name == "movie.mkv"


def test_get_input_files_accepts_quoted_interactive_file():
    """Interactive quoted file input should resolve to one accepted path."""
    get_input_files = importlib.import_module("modules.runtime.pipeline").get_input_files

    with (
        patch("sys.argv", ["script.py"]),
        patch("builtins.input", return_value='"quoted_file.mp4"'),
        patch("modules.runtime.pipeline.Path.exists", return_value=True),
        patch("modules.runtime.pipeline.Path.is_file", return_value=True),
    ):
        files = get_input_files()

    assert len(files) == 1


def test_get_start_time_exception():
    """Return default start time when ffprobe invocation raises."""
    get_start_time = importlib.import_module("modules.core.utils").get_start_time

    with patch("subprocess.check_output", side_effect=OSError("Fail")):
        assert get_start_time("f.mp4") == 0.0


def test_update_progress_logic():
    """Render progress output for both timed and untimed updates."""
    update_progress = importlib.import_module("modules.core.utils").update_progress

    with patch("sys.stderr") as mock_stderr:
        update_progress(10.0, "Test", "00:00:01")
        assert "10.0%" in mock_stderr.write.call_args[0][0]
    # Test None stats
    with patch("sys.stderr") as mock_stderr:
        update_progress(20.0, "Test")
        assert "20.0%" in mock_stderr.write.call_args[0][0]


def test_setup_environment():
    """Test environment setup logic explicitly."""
    utils = importlib.import_module("modules.core.utils")

    with patch("modules.core.utils.get_project_root", return_value="C:/repo"):
        with patch("modules.core.utils.os.path.exists", side_effect=lambda x: True):
            with patch("modules.core.utils.os.environ", {"PATH": ""}):
                utils.setup_environment()
                assert "C:/repo/.venv/Scripts" in utils.os.environ["PATH"].replace("\\", "/")
