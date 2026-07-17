"""Execution-path integration tests for pipeline happy flow and summaries."""

import importlib
import stat
from pathlib import Path
from unittest.mock import MagicMock, patch


def _collect_batch_summary_lines(ad, files, fake_results):
    """Run main with fake batch results and return captured summary lines."""
    with (
        patch("modules.runtime.pipeline.setup_environment"),
        patch("modules.runtime.pipeline.get_cpu_name", return_value="cpu"),
        patch("modules.runtime.pipeline.get_gpu_name", return_value="gpu"),
        patch("modules.runtime.pipeline._show_banner"),
        patch("modules.runtime.pipeline.check_requirements"),
        patch("modules.runtime.pipeline.get_input_files", return_value=files),
        patch("modules.runtime.pipeline.process_video", side_effect=fake_results),
        patch("modules.runtime.pipeline.log_info") as mock_log_info,
        patch("sys.argv", ["script.py", "a.mp4"]),
    ):
        ad.main()

    return [call.args[0] for call in mock_log_info.call_args_list if call.args]


def _build_batch_summary_fixture():
    """Return input files and result rows used by batch summary tests."""
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
    return files, fake_results


def test_process_batch_appends_failed_row_for_exceptions(monkeypatch):
    """Batch exceptions should still produce a failed result row."""
    pipeline = importlib.import_module("modules.runtime.pipeline")
    process_batch = getattr(pipeline, "_process_batch")
    input_files = [Path("broken.mp4")]

    monkeypatch.setattr(pipeline, "_log_batch_result", lambda *args, **kwargs: None)
    monkeypatch.setattr(pipeline, "process_video", MagicMock(side_effect=RuntimeError("boom")))
    monkeypatch.setattr(pipeline, "log_error", MagicMock())

    results = process_batch(input_files)

    assert results == [
        {
            "input": input_files[0],
            "output": None,
            "status": "failed",
            "elapsed_sec": results[0]["elapsed_sec"],
            "duration_sec": 0.0,
            "speed_x": None,
        }
    ]


def test_process_video_happy_path_execution(ad):
    """
    Test the Rendering Loop (Happy Path) with proper mocking.
    This test covers the happy path execution without using real subprocesses.
    """
    mock_stat = MagicMock()
    mock_stat.st_size = 5000
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
    """Batch runs should print aggregate summary counts and totals."""
    files, fake_results = _build_batch_summary_fixture()
    logged_output = "\n".join(_collect_batch_summary_lines(ad, files, fake_results))
    assert "[BATCH SUMMARY]" in logged_output
    assert "Success : 1" in logged_output
    assert "Failed  : 1" in logged_output


def test_main_logs_batch_summary_speed_section(ad):
    """Batch summary should include speed and video section headings."""
    files, fake_results = _build_batch_summary_fixture()
    logged_output = "\n".join(_collect_batch_summary_lines(ad, files, fake_results))
    assert "Speed   : 2.00x" in logged_output
    assert "Videos  :" in logged_output


def test_main_logs_batch_summary_video_rows(ad):
    """Batch summary should include one formatted row per processed video."""
    files, fake_results = _build_batch_summary_fixture()
    logged_output = "\n".join(_collect_batch_summary_lines(ad, files, fake_results))
    assert "a.mp4 -> SUCCESS (speed: 2.00x, output: a_out.mov)" in logged_output
    assert "b.mp4 -> FAILED (speed: 0.50x, output: b_out.mov)" in logged_output
