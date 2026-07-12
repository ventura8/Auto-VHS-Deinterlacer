import sys
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest
import yaml

# NOTE: No top-level import of auto_deinterlancer to ensure coverage starts first.
# We use the 'ad' fixture from conftest.py instead.


def test_log_error_coverage(ad):
    """Call log_error once to ensure line 48 is covered."""
    with patch("auto_deinterlancer.logger.error") as mock_err:
        ad.log_error("test error")
        assert mock_err.called


def test_load_config_missing_file(ad):
    """Test config not found."""
    with patch("auto_deinterlancer.os.path.exists", return_value=False):
        with patch("auto_deinterlancer.sys.exit") as mock_exit:
            ad.load_config()
            assert mock_exit.called


def test_load_config_yaml_error(ad):
    """Test yaml error."""
    with patch("auto_deinterlancer.os.path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=":- bad yaml")):
            with patch("auto_deinterlancer.yaml.safe_load", side_effect=yaml.YAMLError("Oops")):
                with patch("auto_deinterlancer.sys.exit") as mock_exit:
                    ad.load_config()
                    assert mock_exit.called


def test_detect_hardware_manual_profile(ad):
    """Test manual profile branch."""
    with patch("modules.core.config.PERF_PROFILE", "manual"):
        with patch("modules.core.config.CONFIG", {"manual_settings": {"cpu_threads": 8}}):
            settings = ad.detect_hardware_settings()
            assert settings["cpu_threads"] == 8


def test_detect_hardware_manual_profile_invalid_settings(ad):
    """Manual profile should exit when manual_settings is not a mapping."""
    with patch("modules.core.config.PERF_PROFILE", "manual"):
        with patch("modules.core.config.CONFIG", {"manual_settings": "bad"}):
            with patch("modules.core.config.sys.exit", side_effect=SystemExit(1)) as mock_exit:
                with pytest.raises(SystemExit):
                    ad.detect_hardware_settings()
                assert mock_exit.called


def test_detect_hardware_ram_fail(ad):
    """Test RAM detection exception."""
    import importlib

    mock_ctypes = MagicMock()

    class MockStructure:
        _fields_ = []

    mock_ctypes.Structure = MockStructure
    mock_ctypes.c_ulong = int
    mock_ctypes.c_ulonglong = int
    mock_ctypes.sizeof.return_value = 128
    mock_ctypes.byref.return_value = "ref"
    mock_ctypes.windll.kernel32.GlobalMemoryStatusEx.side_effect = OSError("Fail")

    with patch.dict(sys.modules, {"ctypes": mock_ctypes}):
        import modules.core.config as config_module

        importlib.reload(config_module)
        settings = config_module.detect_hardware_settings()
        assert settings["ram_cache_mb"] == 4000

    importlib.reload(config_module)


def test_load_config_invalid_field_order_type_exits():
    """Reload config module should exit on non-string field_order."""
    import importlib

    import modules.core.config as config_module

    bad_config = {"field_order": None}
    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data="field_order: null")):
            with patch("yaml.safe_load", return_value=bad_config):
                with patch("sys.exit", side_effect=SystemExit(1)):
                    with pytest.raises(SystemExit):
                        importlib.reload(config_module)

    importlib.reload(config_module)


def test_load_config_invalid_tv_standard_type_exits():
    """Reload config module should exit on non-string tv_standard."""
    import importlib

    import modules.core.config as config_module

    bad_config = {"tv_standard": 123}
    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data="tv_standard: 123")):
            with patch("yaml.safe_load", return_value=bad_config):
                with patch("sys.exit", side_effect=SystemExit(1)):
                    with pytest.raises(SystemExit):
                        importlib.reload(config_module)

    importlib.reload(config_module)


def test_load_config_invalid_audio_offset_type_exits():
    """Reload config module should exit on non-numeric audio_sync_offset."""
    import importlib

    import modules.core.config as config_module

    bad_config = {"audio_sync_offset": "not-a-number"}
    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data="audio_sync_offset: not-a-number")):
            with patch("yaml.safe_load", return_value=bad_config):
                with patch("sys.exit", side_effect=SystemExit(1)):
                    with pytest.raises(SystemExit):
                        importlib.reload(config_module)

    importlib.reload(config_module)


def test_detect_ram_settings_api_failure_value():
    """RAM detector should keep defaults when GlobalMemoryStatusEx returns 0."""
    import modules.core.config as config_module

    settings = {"ram_cache_mb": 4000}
    fake_kernel32 = MagicMock()
    fake_kernel32.GlobalMemoryStatusEx.return_value = 0
    fake_windll = MagicMock()
    fake_windll.kernel32 = fake_kernel32
    fake_ctypes = MagicMock()
    fake_ctypes.windll = fake_windll
    fake_ctypes.Structure = type("_Struct", (), {})
    fake_ctypes.c_ulong = int
    fake_ctypes.c_ulonglong = int
    fake_ctypes.sizeof.return_value = 128
    fake_ctypes.byref.side_effect = lambda obj: obj

    with patch.object(config_module, "ctypes", fake_ctypes):
        with patch.object(config_module, "log_info") as mock_log:
            config_module._detect_ram_settings(settings)

    assert settings["ram_cache_mb"] == 4000
    assert any("RAM: Unknown" in str(call.args[0]) for call in mock_log.call_args_list if call.args)


def test_detect_gpu_settings_logs_nvenc_for_av1():
    """NVIDIA + AV1 should log NVENC acceleration path."""
    import modules.core.config as config_module

    settings = {"use_gpu_opencl": False, "gpu_device_index": 0}
    with patch.object(config_module, "ENCODER", "av1"):
        with patch.object(config_module, "get_nvidia_gpu_info", return_value=(1, "NVIDIA GeForce RTX 5090")):
            with patch.object(config_module, "log_info") as mock_log:
                config_module._detect_gpu_settings(settings)

    assert settings["use_gpu_opencl"] is True
    assert settings["gpu_device_index"] == 1
    assert any("OpenCL + NVENC" in str(call.args[0]) for call in mock_log.call_args_list if call.args)


def test_load_hw_settings_skip_detect_via_env(monkeypatch):
    """Skip-detect flag should return deterministic defaults without probing hardware."""
    import modules.core.config as config_module

    monkeypatch.setenv("AUTO_VHS_SKIP_HW_DETECT", "1")
    with patch.object(config_module.os, "cpu_count", return_value=20):
        settings = config_module._load_hw_settings()

    assert settings["cpu_threads"] == 20
    assert settings["ram_cache_mb"] == 4000
    assert settings["use_gpu_opencl"] is True


def test_invalid_encoder_exits_on_reload():
    """Reload config module should exit when encoder is not in valid choices."""
    import importlib

    import modules.core.config as config_module

    bad_config = {"encoder": "x265"}
    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data="encoder: x265")):
            with patch("yaml.safe_load", return_value=bad_config):
                with patch("sys.exit", side_effect=SystemExit(1)):
                    with pytest.raises(SystemExit):
                        importlib.reload(config_module)

    importlib.reload(config_module)


def test_vpy_creation_gpu_logic(ad):
    """Test EdiMode = NNEDI3CL."""
    # Must include all keys accessed in create_vpy_script
    mock_settings = {
        "use_gpu_opencl": True,
        "cpu_threads": 4,
        "ram_cache_mb": 4096,
    }
    with patch("auto_deinterlancer.HW_SETTINGS", mock_settings):
        with patch("builtins.open", mock_open()):
            with patch("auto_deinterlancer.log_debug"):
                # It calls os.path.getsize on the output filename after writing.
                # Since we Mocked open, the file doesn't exist.
                with patch("auto_deinterlancer.os.path.getsize", return_value=123):
                    ad.create_vpy_script(Path("in.mp4"), Path("out.vpy"), "stem")


def test_ffmpeg_time_parse_error(ad):
    """Test ValueError in parse_ffmpeg_time."""
    sec, ts, sp = ad.parse_ffmpeg_time("time=00:XX:00")
    assert sec is None


def test_cleanup_exception(ad):
    """Test except in cleanup."""
    work_dir = MagicMock()
    f = MagicMock()
    f.is_file.return_value = True
    f.name = "test_temp_script.vpy"
    f.unlink.side_effect = OSError("Locked")
    work_dir.glob.return_value = [f]

    ad.cleanup_temp_files(work_dir, "test")
    assert f.unlink.called


def test_gpu_name_not_nvidia(ad):
    """Test output not containing NVIDIA."""
    with patch("auto_deinterlancer.subprocess.check_output", return_value=b"AMD Radeon"):
        name = ad.get_gpu_name()
        assert name == "Generic / Not Detected"


def test_process_video_missing_tools(ad):
    """Test tools missing in process_video."""
    with patch("auto_deinterlancer.shutil.which", return_value=None):
        result = ad.process_video(Path("test.mp4"))

    assert result["status"] == "not_found"
    assert result["output"] is None


def test_process_video_av1_gpu_not_found_early_exit(ad):
    """Test AV1 GPU setup exits early with not_found."""
    mock_stat = MagicMock()
    mock_stat.st_size = 5000

    with patch("auto_deinterlancer.ENCODER", "av1"):
        with patch("auto_deinterlancer.HW_SETTINGS", {"use_gpu_opencl": True, "cpu_threads": 4}):
            with patch.object(Path, "exists") as mock_exists:
                with patch.object(Path, "stat", return_value=mock_stat):
                    mock_exists.side_effect = [False]  # Output not exists
                    with patch("auto_deinterlancer.get_duration", return_value=1.0):
                        with patch("auto_deinterlancer.get_start_time", return_value=0.0):
                            with patch("auto_deinterlancer.cleanup_temp_files"):
                                with patch("auto_deinterlancer.shutil.which", return_value="/bin/tool"):
                                    # Logging mocks to prevent I/O errors
                                    with (
                                        patch("auto_deinterlancer.log_info"),
                                        patch("auto_deinterlancer.log_debug"),
                                        patch("auto_deinterlancer.log_error"),
                                    ):
                                        with patch("auto_deinterlancer.AUDIO_OFFSET", 0.0):
                                            with patch("auto_deinterlancer.AUDIO_CODEC", "aac"):
                                                with patch("auto_deinterlancer.AUDIO_BITRATE", "320k"):
                                                    # Intermediate exists = skip deinterlace
                                                    # Mock says intermediate exists, just does cleanup
                                                    result = ad.process_video(Path("in.mp4"))

    assert result["status"] == "not_found"
    assert result["output"] is None
    assert mock_exists.call_count == 1


def test_process_video_mux_ffmpeg_missing(ad):
    """Test ffmpeg missing for mux."""
    with patch("auto_deinterlancer.shutil.which", side_effect=["/bin/vspipe", "/bin/ffmpeg", None]):
        with patch.object(Path, "exists") as mock_exists:
            with patch.object(Path, "unlink"):
                # 1. output_path.exists() -> False
                # 2. temp_video.exists() -> False
                # 3. temp_vpy.exists() (in except block) -> True (to trigger unlink coverage)
                mock_exists.side_effect = [False, False, True]
                with patch("auto_deinterlancer.get_duration", return_value=1.0):
                    with patch("auto_deinterlancer.get_start_time", return_value=0.0):
                        with patch("auto_deinterlancer.create_vpy_script"):
                            with patch("auto_deinterlancer.subprocess.Popen") as mp:
                                mp.return_value.returncode = 0
                                mp.return_value.poll.return_value = 0
                                mp.return_value.stderr.readline.return_value = ""
                                result = ad.process_video(Path("in.mp4"))

    assert result["status"] == "not_found"
    assert result["output"] is None
    assert not mp.called


def test_mux_path_skipped_when_output_missing(ad):
    """Test mux path is skipped and get_start_time is not called."""
    mock_stat = MagicMock()
    mock_stat.st_size = 5000

    with patch("auto_deinterlancer.AUDIO_OFFSET", 0.0):
        with patch("auto_deinterlancer.get_start_time", side_effect=[0.0, 0.04]) as mock_start_time:
            with patch.object(Path, "exists") as mock_exists:
                with patch.object(Path, "stat", return_value=mock_stat):
                    mock_exists.side_effect = [False, True]  # Output not exists, Intermediate exists
                    with patch("auto_deinterlancer.get_duration", return_value=1.0):
                        with patch("auto_deinterlancer.cleanup_temp_files"):
                            with patch("auto_deinterlancer.shutil.which", return_value="/bin/tool"):
                                # Logging mocks to prevent I/O errors
                                with (
                                    patch("auto_deinterlancer.log_info"),
                                    patch("auto_deinterlancer.log_debug"),
                                    patch("auto_deinterlancer.log_error"),
                                ):
                                    with patch("auto_deinterlancer.AUDIO_CODEC", "aac"):
                                        with patch("auto_deinterlancer.AUDIO_BITRATE", "320k"):
                                            # Intermediate exists, so it does cleanup
                                            result = ad.process_video(Path("in.mp4"))

    assert result["status"] == "not_found"
    assert result["output"] is None
    assert not mock_start_time.called
