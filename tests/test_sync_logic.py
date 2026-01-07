from unittest.mock import patch, MagicMock
from pathlib import Path


def test_drift_logic_negligible(ad):
    """Test that small drift (<0.010s) results in speed_factor=1.0"""
    input_p = Path("test.mp4")

    with patch('modules.pipeline.get_vpy_info', return_value=(3000, 30.0, 720, 576, 'YUV420P10')):  # 100.0s NEW video
        with patch('modules.pipeline.get_duration', return_value=100.005):  # 100.005s SRC audio (Drift 0.005)
            with patch('modules.pipeline.create_vpy_script'):
                    with patch('modules.pipeline.shutil.which', return_value="/bin/tool"):
                        with patch('modules.pipeline.cleanup_temp_files'):
                            with patch('subprocess.Popen') as mock_popen:
                                # Setup Popen mocks
                                p1 = MagicMock()
                                p1.stderr.readline.return_value = b""
                                p2 = MagicMock()
                                p2.stderr.readline.side_effect = ["", "", ""]
                                p2.poll.side_effect = [None, 0, 0]
                                p2.returncode = 0
                                mock_popen.side_effect = [p1, p2]

                                with patch('os.path.exists', return_value=True):  # vspipe exists
                                    # input check, output check
                                    with patch('modules.pipeline.Path.exists', side_effect=[True, False, False]):
                                        with patch('modules.pipeline.Path.stat') as mock_stat:
                                            import stat
                                            mock_stat.return_value.st_mode = stat.S_IFREG
                                            mock_stat.return_value.st_size = 5000

                                        test_config = {
                                            "auto_drift_correction": True,
                                            "audio_sync_offset": 0.0,
                                            "encoder": "prores",
                                            "audio_codec": "aac",
                                            "audio_bitrate": "320k"
                                        }
                                        with patch('modules.pipeline.CONFIG', test_config):
                                            with patch('modules.pipeline.HW_SETTINGS', {
                                                "cpu_threads": 4,
                                                "use_gpu_opencl": False
                                            }):
                                                with patch('modules.config.AUDIO_OFFSET', 0.0):
                                                    with patch('modules.config.ENCODER', 'prores'):
                                                        with patch('modules.config.AUDIO_CODEC', 'aac'):
                                                            with patch('modules.config.AUDIO_BITRATE', '320k'):
                                                                ad.process_video(input_p)

                                                                # Check 2nd Popen call (FFmpeg)
                                                                assert mock_popen.call_count == 2
                                                                args, _ = mock_popen.call_args_list[1]
                                                                cmd_str = " ".join(args[0])
                                                                # Expect NO atempo filter for negligible drift
                                                                assert "atempo" not in cmd_str


def test_drift_logic_negative_ignored(ad):
    """Test that negative drift (Audio < Video) is IGNORED (Truncation assumption)."""
    input_p = Path("test.mp4")

    # Video: 100.20s -> 3006 frames @ 30fps
    # Audio: 100.00s
    # Drift: Audio is shorter (-0.2s).
    # Logic: speed_factor = 100 / 100.2 = ~0.998.
    # NEW BEHAVIOR: Should IGNORE and use 1.0.

    with patch('modules.pipeline.get_vpy_info', return_value=(3006, 30.0, 720, 576, 'YUV420P10')):  # 100.2s
        with patch('modules.pipeline.get_duration', return_value=100.0):  # 100.0s
            with patch('modules.pipeline.create_vpy_script'):
                    with patch('modules.pipeline.shutil.which', return_value="/bin/tool"):
                        with patch('modules.pipeline.cleanup_temp_files'):
                            with patch('subprocess.Popen') as mock_popen:
                                p1 = MagicMock()
                                p1.stderr.readline.return_value = b""
                                p2 = MagicMock()
                                p2.stderr.readline.side_effect = ["", "", ""]
                                p2.poll.side_effect = [None, 0, 0]
                                p2.returncode = 0
                                mock_popen.side_effect = [p1, p2]

                                with patch('os.path.exists', return_value=True):
                                    with patch('modules.pipeline.Path.exists', side_effect=[True, False, False]):

                                        with patch('modules.config.CONFIG', {
                                            "auto_drift_correction": True,
                                            "drift_guard_thresholds": {
                                                "max_drift_percent": 1.5,
                                                "min_drift_seconds": 0.010
                                            },
                                            "audio_sync_offset": 0.0
                                        }):
                                            with patch('modules.config.HW_SETTINGS', {
                                                "cpu_threads": 4,
                                                "use_gpu_opencl": False
                                            }):
                                                with patch('modules.config.AUDIO_OFFSET', 0.0):
                                                    with patch('modules.config.ENCODER', 'prores'):
                                                        with patch('modules.config.AUDIO_CODEC', 'aac'):
                                                            with patch('modules.config.AUDIO_BITRATE', '320k'):
                                                                ad.process_video(input_p)

                                                                # Assert ignored
                                                                args, _ = mock_popen.call_args_list[1]
                                                                cmd_str = " ".join(args[0])
                                                                assert "atempo" not in cmd_str


def test_drift_logic_positive_correction(ad):
    """Test that positive drift (Audio > Video) IS corrected (Dropped frames)."""
    input_p = Path("test.mp4")

    # Video: 100.00s
    # Audio: 100.20s
    # Drift: Audio is longer (Video dropped frames).
    # Logic: speed_factor = 100.2 / 100.0 = 1.002.
    # SHOULD CORRECT.

    with patch('modules.pipeline.get_vpy_info', return_value=(3000, 30.0, 720, 576, 'YUV420P10')):  # 100.0s
        with patch('modules.pipeline.get_duration', return_value=100.2):  # 100.2s
            with patch('modules.pipeline.create_vpy_script'):
                    with patch('modules.pipeline.shutil.which', return_value="/bin/tool"):
                        with patch('modules.pipeline.cleanup_temp_files'):
                            with patch('subprocess.Popen') as mock_popen:
                                p1 = MagicMock()
                                p1.stderr.readline.return_value = b""
                                p2 = MagicMock()
                                p2.stderr.readline.side_effect = ["", "", ""]
                                p2.poll.side_effect = [None, 0, 0]
                                p2.returncode = 0
                                mock_popen.side_effect = [p1, p2]

                                with patch('os.path.exists', return_value=True):
                                    with patch('modules.pipeline.Path.exists', side_effect=[True, False, False]):

                                        with patch('modules.config.CONFIG', {
                                            "auto_drift_correction": True,
                                            "drift_guard_thresholds": {
                                                "max_drift_percent": 1.5,
                                                "min_drift_seconds": 0.010
                                            },
                                            "audio_sync_offset": 0.0
                                        }):
                                            with patch('modules.config.HW_SETTINGS', {
                                                "cpu_threads": 4,
                                                "use_gpu_opencl": False
                                            }):
                                                with patch('modules.config.AUDIO_OFFSET', 0.0):
                                                    with patch('modules.config.ENCODER', 'prores'):
                                                        with patch('modules.config.AUDIO_CODEC', 'aac'):
                                                            with patch('modules.config.AUDIO_BITRATE', '320k'):
                                                                ad.process_video(input_p)

                                                                # Assert Corrected (Speed > 1.0)
                                                                args, _ = mock_popen.call_args_list[1]
                                                                cmd_str = " ".join(args[0])
                                                                assert "atempo=1.002" in cmd_str


def test_drift_guard_excessive(ad):
    """Test that excessive drift (>1.5%) is IGNORED."""
    input_p = Path("test.mp4")

    # Audio: 102.0s
    # Video: 100.0s
    # Drift 2% (Speed factor 1.02)

    with patch('modules.pipeline.get_vpy_info', return_value=(3000, 30.0, 720, 576, 'YUV420P10')):  # 100.0s
        with patch('modules.pipeline.get_duration', return_value=102.0):  # 102.0s
            with patch('modules.pipeline.create_vpy_script'):
                    with patch('modules.pipeline.shutil.which', return_value="/bin/tool"):
                        with patch('modules.pipeline.cleanup_temp_files'):
                            with patch('subprocess.Popen') as mock_popen:
                                p1 = MagicMock()
                                p1.stderr.readline.return_value = b""
                                p2 = MagicMock()
                                p2.stderr.readline.side_effect = ["", "", ""]
                                p2.poll.side_effect = [None, 0, 0]
                                p2.returncode = 0
                                mock_popen.side_effect = [p1, p2]

                                with patch('os.path.exists', return_value=True):
                                    with patch('modules.pipeline.Path.exists', side_effect=[True, False, False]):

                                        with patch('modules.config.CONFIG', {
                                            "auto_drift_correction": True,
                                            "drift_guard_thresholds": {
                                                "max_drift_percent": 1.5,
                                                "min_drift_seconds": 0.010
                                            },
                                            "audio_sync_offset": 0.0
                                        }):
                                            with patch('modules.config.HW_SETTINGS', {
                                                "cpu_threads": 4,
                                                "use_gpu_opencl": False
                                            }):
                                                with patch('modules.config.AUDIO_OFFSET', 0.0):
                                                    with patch('modules.config.ENCODER', 'prores'):
                                                        with patch('modules.config.AUDIO_CODEC', 'aac'):
                                                            with patch('modules.config.AUDIO_BITRATE', '320k'):
                                                                ad.process_video(input_p)

                                                                # Assert ignored
                                                                args, _ = mock_popen.call_args_list[1]
                                                                cmd_str = " ".join(args[0])
                                                                assert "atempo" not in cmd_str


def test_drift_disabled(ad):
    """Test that drift correction can be disabled via config"""
    input_p = Path("test.mp4")

    with patch('modules.pipeline.get_vpy_info', return_value=(3000, 30.0, 720, 576, 'YUV420P10')):  # 100.0s
        with patch('modules.pipeline.get_duration', return_value=100.5):  # 0.5s drift (Valid but disabled)
            with patch('modules.pipeline.create_vpy_script'):
                    with patch('modules.pipeline.shutil.which', return_value="/bin/tool"):
                        with patch('modules.pipeline.cleanup_temp_files'):
                            with patch('subprocess.Popen') as mock_popen:
                                p1 = MagicMock()
                                p1.stderr.readline.return_value = b""
                                p2 = MagicMock()
                                p2.stderr.readline.side_effect = ["", "", ""]
                                p2.poll.side_effect = [None, 0, 0]
                                p2.returncode = 0
                                mock_popen.side_effect = [p1, p2]

                                with patch('os.path.exists', return_value=True):
                                    with patch('modules.pipeline.Path.exists', side_effect=[True, False, False]):
                                        with patch('modules.pipeline.Path.stat') as mock_stat:
                                            import stat
                                            mock_stat.return_value.st_mode = stat.S_IFREG
                                            mock_stat.return_value.st_size = 5000

                                        test_config = {
                                            "auto_drift_correction": False,
                                            "audio_sync_offset": 0.0
                                        }
                                        with patch('modules.pipeline.CONFIG', test_config):
                                            with patch('modules.pipeline.HW_SETTINGS', {
                                                "cpu_threads": 4,
                                                "use_gpu_opencl": False
                                            }):
                                                with patch('modules.config.AUDIO_OFFSET', 0.0):
                                                    with patch('modules.config.ENCODER', 'prores'):
                                                        with patch('modules.config.AUDIO_CODEC', 'aac'):
                                                            with patch('modules.config.AUDIO_BITRATE', '320k'):
                                                                ad.process_video(input_p)

                                                                args, _ = mock_popen.call_args_list[1]
                                                                cmd_str = " ".join(args[0])
                                                                assert "atempo" not in cmd_str
