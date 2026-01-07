import sys
import yaml
from unittest.mock import MagicMock, patch, mock_open
from pathlib import Path

# NOTE: No top-level import of auto_deinterlancer to ensure coverage starts first.
# We use the 'ad' fixture from conftest.py instead.


def test_log_error_coverage(ad):
    """Call log_error once to ensure line 48 is covered."""
    with patch('auto_deinterlancer.logger.error') as mock_err:
        ad.log_error("test error")
        assert mock_err.called


def test_load_config_missing_file(ad):
    """Test config not found."""
    with patch('auto_deinterlancer.os.path.exists', return_value=False):
        with patch('auto_deinterlancer.sys.exit') as mock_exit:
            ad.load_config()
            assert mock_exit.called


def test_load_config_yaml_error(ad):
    """Test yaml error."""
    with patch('auto_deinterlancer.os.path.exists', return_value=True):
        with patch('builtins.open', mock_open(read_data=":- bad yaml")):
            with patch('auto_deinterlancer.yaml.safe_load', side_effect=yaml.YAMLError("Oops")):
                with patch('auto_deinterlancer.sys.exit') as mock_exit:
                    ad.load_config()
                    assert mock_exit.called


def test_detect_hardware_manual_profile(ad):
    """Test manual profile branch."""
    with patch('modules.config.PERF_PROFILE', 'manual'):
        with patch('modules.config.CONFIG', {"manual_settings": {"cpu_threads": 8}}):
            settings = ad.detect_hardware_settings()
            assert settings["cpu_threads"] == 8


def test_detect_hardware_ram_fail(ad):
    """Test RAM detection exception."""
    mock_ctypes = MagicMock()
    # The code does: kernel32.GlobalMemoryStatusEx
    mock_ctypes.windll.kernel32.GlobalMemoryStatusEx.side_effect = Exception("Fail")

    with patch.dict(sys.modules, {'ctypes': mock_ctypes}):
        settings = ad.detect_hardware_settings()
        assert settings["ram_cache_mb"] == 4000


def test_vpy_creation_gpu_logic(ad):
    """Test EdiMode = NNEDI3CL."""
    # Must include all keys accessed in create_vpy_script
    mock_settings = {
        "use_gpu_opencl": True,
        "cpu_threads": 4,
        "ram_cache_mb": 4096,
    }
    with patch('auto_deinterlancer.HW_SETTINGS', mock_settings):
        with patch('builtins.open', mock_open()):
            with patch('auto_deinterlancer.log_debug'):
                # It calls os.path.getsize on the output filename after writing.
                # Since we Mocked open, the file doesn't exist.
                with patch('auto_deinterlancer.os.path.getsize', return_value=123):
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
    f.unlink.side_effect = Exception("Locked")
    work_dir.glob.return_value = [f]

    ad.cleanup_temp_files(work_dir, "test")
    assert f.unlink.called


def test_gpu_name_not_nvidia(ad):
    """Test output not containing NVIDIA."""
    with patch('auto_deinterlancer.subprocess.check_output', return_value=b"AMD Radeon"):
        name = ad.get_gpu_name()
        assert name == "Generic / Not Detected"


def test_process_video_missing_tools(ad):
    """Test tools missing in process_video."""
    with patch('auto_deinterlancer.shutil.which', return_value=None):
        ad.process_video(Path("test.mp4"))


def test_process_video_av1_gpu_coverage(ad):
    """Test AV1 NVENC path."""
    mock_stat = MagicMock()
    mock_stat.st_size = 5000

    with patch('auto_deinterlancer.ENCODER', "av1"):
        with patch('auto_deinterlancer.HW_SETTINGS', {"use_gpu_opencl": True, "cpu_threads": 4}):
            with patch.object(Path, 'exists') as mock_exists:
                with patch.object(Path, 'stat', return_value=mock_stat):
                    mock_exists.side_effect = [False, True]  # Output not exists, Intermediate exists
                    with patch('auto_deinterlancer.get_duration', return_value=1.0):
                        with patch('auto_deinterlancer.get_start_time', return_value=0.0):
                            with patch('auto_deinterlancer.cleanup_temp_files'):
                                with patch('auto_deinterlancer.shutil.which', return_value="/bin/tool"):
                                    # Logging mocks to prevent I/O errors
                                    with patch('auto_deinterlancer.log_info'), \
                                            patch('auto_deinterlancer.log_debug'), \
                                            patch('auto_deinterlancer.log_error'):
                                        with patch('auto_deinterlancer.AUDIO_OFFSET', 0.0):
                                            with patch('auto_deinterlancer.AUDIO_CODEC', 'aac'):
                                                with patch('auto_deinterlancer.AUDIO_BITRATE', '320k'):
                                                    # Intermediate exists = skip deinterlace
                                                    # Mock says intermediate exists, just does cleanup
                                                    ad.process_video(Path("in.mp4"))


def test_process_video_mux_ffmpeg_missing(ad):
    """Test ffmpeg missing for mux."""
    with patch('auto_deinterlancer.shutil.which', side_effect=["/bin/vspipe", "/bin/ffmpeg", None]):
        with patch.object(Path, 'exists') as mock_exists:
            with patch.object(Path, 'unlink'):
                # 1. output_path.exists() -> False
                # 2. temp_video.exists() -> False
                # 3. temp_vpy.exists() (in except block) -> True (to trigger unlink coverage)
                mock_exists.side_effect = [False, False, True]
                with patch('auto_deinterlancer.get_duration', return_value=1.0):
                    with patch('auto_deinterlancer.get_start_time', return_value=0.0):
                        with patch('auto_deinterlancer.create_vpy_script'):
                            with patch('auto_deinterlancer.subprocess.Popen') as mp:
                                mp.return_value.returncode = 0
                                mp.return_value.poll.return_value = 0
                                mp.return_value.stderr.readline.return_value = ""
                                ad.process_video(Path("in.mp4"))


def test_placeholder():
    pass


def test_mux_anull_branch(ad):
    """Test anull branch in muxing."""
    mock_stat = MagicMock()
    mock_stat.st_size = 5000

    with patch('auto_deinterlancer.AUDIO_OFFSET', 0.0):
        with patch('auto_deinterlancer.get_start_time', side_effect=[0.0, 0.04]):
            with patch.object(Path, 'exists') as mock_exists:
                with patch.object(Path, 'stat', return_value=mock_stat):
                    mock_exists.side_effect = [False, True]  # Output not exists, Intermediate exists
                    with patch('auto_deinterlancer.get_duration', return_value=1.0):
                        with patch('auto_deinterlancer.cleanup_temp_files'):
                            with patch('auto_deinterlancer.shutil.which', return_value="/bin/tool"):
                                # Logging mocks to prevent I/O errors
                                with patch('auto_deinterlancer.log_info'), \
                                        patch('auto_deinterlancer.log_debug'), \
                                        patch('auto_deinterlancer.log_error'):
                                    with patch('auto_deinterlancer.AUDIO_CODEC', 'aac'):
                                        with patch('auto_deinterlancer.AUDIO_BITRATE', '320k'):
                                            # Intermediate exists, so it does cleanup
                                            ad.process_video(Path("in.mp4"))
