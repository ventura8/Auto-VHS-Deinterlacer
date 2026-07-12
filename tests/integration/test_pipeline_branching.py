from pathlib import Path
from unittest.mock import MagicMock, patch


def test_build_ffmpeg_cmd_av1_with_atempo_and_adelay():
    from modules.runtime import pipeline

    with patch("modules.runtime.pipeline.ENCODER", "av1"):
        with patch("modules.runtime.pipeline.HW_SETTINGS", {"cpu_threads": 32}):
            with patch("modules.runtime.pipeline.AUDIO_OFFSET", 1.25):
                with patch("modules.runtime.pipeline.AUDIO_CODEC", "aac"):
                    with patch("modules.runtime.pipeline.AUDIO_BITRATE", "256k"):
                        cmd = pipeline._build_ffmpeg_cmd(
                            Path("input.mp4"),
                            Path("out_part.mkv"),
                            atempo=1.01,
                            fps=29.97,
                            width=720,
                            height=576,
                            pixel_format="yuv420p10le",
                        )

    cmd_str = " ".join(cmd)
    assert "libsvtav1" in cmd_str
    assert "-threads:v 32" in cmd_str
    assert "-svtav1-params lp=32" in cmd_str
    assert "atempo=1.010000" in cmd_str
    assert "adelay=1250|1250" in cmd_str


def test_build_ffmpeg_cmd_prores_uses_hw_thread_count():
    from modules.runtime import pipeline

    with patch("modules.runtime.pipeline.ENCODER", "prores"):
        with patch("modules.runtime.pipeline.HW_SETTINGS", {"cpu_threads": 24}):
            cmd = pipeline._build_ffmpeg_cmd(
                Path("input.mp4"),
                Path("out_part.mov"),
                atempo=1.0,
                fps=29.97,
                width=720,
                height=576,
                pixel_format="yuv422p10le",
            )

    cmd_str = " ".join(cmd)
    assert "-threads:v 24" in cmd_str
    assert "prores_ks" in cmd_str


def test_run_encoding_pipeline_python_vspipe_and_cleanup_error():
    from modules.runtime import pipeline

    temp_script = Path("temp_script.vpy")

    p_vspipe = MagicMock()
    p_vspipe.stdout = MagicMock()
    p_vspipe.stderr = MagicMock()
    p_vspipe.wait.return_value = None

    p_ffmpeg = MagicMock()
    p_ffmpeg.returncode = 0
    p_ffmpeg.wait.return_value = None
    p_ffmpeg.stderr = MagicMock()

    popen_vs = MagicMock()
    popen_vs.__enter__.return_value = p_vspipe
    popen_vs.__exit__.return_value = False

    popen_ff = MagicMock()
    popen_ff.__enter__.return_value = p_ffmpeg
    popen_ff.__exit__.return_value = False

    ffmpeg_lines = ["noise"] * 22 + ["frame=   10 fps=25 q=1.0 size=1kB time=00:00:01.00 speed=1.0x"]

    with patch("modules.runtime.pipeline.get_vspipe_env", return_value={"PYTHONHOME": "X", "PYTHONPATH": "Y"}):
        with patch("modules.runtime.pipeline.sys.executable", "python_exe"):
            with patch("subprocess.Popen", side_effect=[popen_vs, popen_ff]):
                with patch("threading.Thread"):
                    with patch("io.TextIOWrapper", return_value=ffmpeg_lines):
                        with patch("modules.runtime.pipeline.parse_ffmpeg_time", return_value=(1.0, "00:00:01,000", "badx")):
                            with patch.object(Path, "exists", return_value=True):
                                with patch("os.remove", side_effect=OSError("cleanup")):
                                    result = pipeline._run_encoding_pipeline(
                                        ["python_exe", "-m", "modules.runtime.vspipe_native", "temp.vpy"],
                                        ["ffmpeg", "-i", "-"],
                                        temp_script,
                                        100.0,
                                    )

    assert result is True


def test_process_video_debug_venv_fallback_and_rename_failure():
    from modules.runtime import pipeline

    input_path = Path("input.mp4")
    mock_stat = MagicMock()
    mock_stat.st_size = 5000
    import stat

    mock_stat.st_mode = stat.S_IFREG

    with patch("modules.runtime.pipeline.DEBUG_MODE", True):
        with patch.object(Path, "exists", side_effect=[True, False, True]):
            with patch.object(Path, "stat", return_value=mock_stat):
                with patch("modules.runtime.pipeline.create_vpy_script"):
                    with patch("modules.runtime.pipeline.shutil.which", return_value="vspipe"):
                        with patch("modules.runtime.pipeline.os.path.exists", return_value=False):
                            with patch("modules.runtime.pipeline.get_vpy_info", return_value=(120, 30.0, 0, 0, "unknown")):
                                with patch("modules.runtime.pipeline._run_encoding_pipeline", return_value=True):
                                    with patch("pathlib.Path.replace", side_effect=OSError("rename failed")):
                                        with patch("modules.runtime.pipeline.log_error") as mock_log_error:
                                            with patch("modules.runtime.pipeline.cleanup_temp_files"):
                                                pipeline.process_video(input_path)
                                                assert mock_log_error.called
