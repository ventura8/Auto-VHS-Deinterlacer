from unittest.mock import patch, MagicMock
from pathlib import Path


def test_process_video_happy_path_execution(ad):
    """
    Test the Rendering Loop (Happy Path) with proper mocking.
    This test covers the happy path execution without using real subprocesses.
    """
    mock_stat = MagicMock()
    mock_stat.st_size = 5000
    import stat
    mock_stat.st_mode = stat.S_IFREG

    input_p = Path("test.mp4")

    with patch.object(Path, 'exists') as mock_exists:
        with patch.object(Path, 'stat', return_value=mock_stat):
            # Output doesn't exist, intermediate doesn't exist
            mock_exists.side_effect = [True, False, False, False, False, False, False]

            with patch('auto_deinterlancer.get_duration', return_value=10.0):
                with patch('auto_deinterlancer.get_start_time', return_value=0.0):
                    with patch('auto_deinterlancer.create_vpy_script'):
                        with patch('auto_deinterlancer.cleanup_temp_files'):
                            with patch('shutil.which', return_value="/bin/tool"):
                                with patch('os.path.exists', return_value=True):
                                    with patch('subprocess.Popen') as mock_popen:
                                        # Setup mock subprocess
                                        p1 = MagicMock()
                                        p1.stdout = MagicMock()
                                        p1.stderr = MagicMock()
                                        p1.stderr.readline.side_effect = [b"Frame 100/1000", b"Frame 500/1000", None]

                                        p2 = MagicMock()
                                        p2.poll.side_effect = [None, None, 0]
                                        # Simulate FFmpeg progress output
                                        p2.stderr.readline.side_effect = [
                                            "frame=100 time=00:17:02.28 speed=2.57x\n",
                                            "frame=500 time=00:35:00.00 speed=2.50x\n",
                                            ""
                                        ]
                                        p2.returncode = 0
                                        mock_popen.side_effect = [p1, p2]

                                        # Mock logging to prevent I/O errors
                                        with patch('auto_deinterlancer.log_info'), \
                                                patch('auto_deinterlancer.log_debug'), \
                                                patch('auto_deinterlancer.log_error'):
                                            with patch('auto_deinterlancer.get_vpy_info', return_value=(3000, 30.0, 720, 576, 'YUV420P10')):
                                                with patch('auto_deinterlancer.update_progress'):
                                                    ad.process_video(input_p)

                                                    # Verify subprocess was called
                                                    assert mock_popen.called
