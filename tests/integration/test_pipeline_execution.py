from pathlib import Path
from unittest.mock import MagicMock, patch


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

    with patch.object(Path, "exists") as mock_exists:
        with patch.object(Path, "stat", return_value=mock_stat):
            # Output doesn't exist, intermediate doesn't exist
            mock_exists.side_effect = [True, False, False, False, False, False, False]

            with patch("modules.runtime.pipeline.get_duration", return_value=10.0):
                with patch("modules.runtime.pipeline.create_vpy_script"):
                    with patch("modules.runtime.pipeline.cleanup_temp_files"):
                        with patch("modules.runtime.pipeline.shutil.which", return_value="/bin/tool"):
                            with patch("os.path.exists", return_value=True):
                                with patch("subprocess.Popen") as mock_popen:
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
                                        "",
                                    ]
                                    p2.returncode = 0
                                    mock_popen.side_effect = [p1, p2]

                                    # Mock logging to prevent I/O errors
                                    with (
                                        patch("auto_deinterlancer.log_info"),
                                        patch("auto_deinterlancer.log_debug"),
                                        patch("auto_deinterlancer.log_error"),
                                    ):
                                        with patch(
                                            "modules.runtime.pipeline.get_vpy_info",
                                            return_value=(3000, 30.0, 720, 576, "YUV420P10"),
                                        ):
                                            with patch(
                                                "modules.runtime.pipeline._run_encoding_pipeline",
                                                return_value=True,
                                            ) as mock_run:
                                                with patch("modules.runtime.pipeline.update_progress"):
                                                    ad.process_video(input_p)

                                                # Verify the encoding step was invoked.
                                                assert mock_run.called


def test_main_logs_batch_summary(ad):
    """Batch runs should print a final aggregate summary."""
    files = [Path("a.mp4"), Path("b.mp4")]
    fake_results = [
        {
            "input": files[0],
            "output": Path("a_out.mov"),
            "status": "success",
            "elapsed_sec": 10.0,
            "duration_sec": 20.0,
            "speed_x": 2.0,
        },
        {
            "input": files[1],
            "output": Path("b_out.mov"),
            "status": "failed",
            "elapsed_sec": 20.0,
            "duration_sec": 10.0,
            "speed_x": 0.5,
        },
    ]

    with patch("modules.runtime.pipeline.setup_environment"):
        with patch("modules.runtime.pipeline.get_cpu_name", return_value="cpu"):
            with patch("modules.runtime.pipeline.get_gpu_name", return_value="gpu"):
                with patch("modules.runtime.pipeline._show_banner"):
                    with patch("modules.runtime.pipeline.check_requirements"):
                        with patch("modules.runtime.pipeline.get_input_files", return_value=files):
                            with patch("modules.runtime.pipeline.process_video", side_effect=fake_results):
                                with patch("modules.runtime.pipeline.log_info") as mock_log_info:
                                    with patch("sys.argv", ["script.py", "a.mp4"]):
                                        ad.main()

    logged_lines = [call.args[0] for call in mock_log_info.call_args_list if call.args]
    assert any("[BATCH SUMMARY]" in line for line in logged_lines)
    assert any("Success : 1" in line for line in logged_lines)
    assert any("Failed  : 1" in line for line in logged_lines)
    assert any("Speed   : 2.00x" in line for line in logged_lines)
    assert any("Videos  :" in line for line in logged_lines)
    assert any("a.mp4 -> SUCCESS (speed: 2.00x, output: a_out.mov)" in line for line in logged_lines)
    assert any("b.mp4 -> FAILED (speed: 0.50x, output: b_out.mov)" in line for line in logged_lines)
