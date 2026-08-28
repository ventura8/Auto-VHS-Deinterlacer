"""Integration tests that cover branch behavior in pipeline helpers."""

import importlib
import stat
from pathlib import Path
from unittest.mock import MagicMock, patch


def test_build_ffmpeg_cmd_av1_with_atempo_and_adelay():
    """Build AV1 command with sync filters and hardware thread propagation."""
    pipeline = importlib.import_module("modules.runtime.pipeline")
    build_ffmpeg_cmd = getattr(pipeline, "_build_ffmpeg_cmd")

    with patch.multiple(
        "modules.runtime.pipeline",
        ENCODER="av1",
        HW_SETTINGS={"cpu_threads": 32},
        AUDIO_OFFSET=1.25,
        AUDIO_CODEC="aac",
        AUDIO_BITRATE="256k",
    ):
        cmd = build_ffmpeg_cmd(
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


def test_build_ffmpeg_cmd_av1_uses_nvenc_when_capable():
    """Build AV1 command with NVENC when hardware detection reports NVIDIA."""
    pipeline = importlib.import_module("modules.runtime.pipeline")
    build_ffmpeg_cmd = getattr(pipeline, "_build_ffmpeg_cmd")

    with patch.multiple(
        "modules.runtime.pipeline",
        ENCODER="av1",
        HW_SETTINGS={"cpu_threads": 32, "has_av1_nvenc": True},
        AUDIO_OFFSET=0.0,
        AUDIO_CODEC="aac",
        AUDIO_BITRATE="256k",
    ):
        cmd = build_ffmpeg_cmd(
            Path("input.mp4"),
            Path("out_part.mkv"),
            atempo=1.0,
            fps=29.97,
            width=720,
            height=576,
            pixel_format="yuv420p10le",
        )

    cmd_str = " ".join(cmd)
    assert "av1_nvenc" in cmd_str
    assert "-threads:v 32" in cmd_str
    assert "-svtav1-params" not in cmd_str


def test_build_ffmpeg_cmd_logs_gpu_path_for_av1_nvenc():
    """AV1 NVENC path should emit a clear GPU usage log line."""
    pipeline = importlib.import_module("modules.runtime.pipeline")
    build_ffmpeg_cmd = getattr(pipeline, "_build_ffmpeg_cmd")

    with patch.multiple(
        "modules.runtime.pipeline",
        ENCODER="av1",
        HW_SETTINGS={"cpu_threads": 32, "has_av1_nvenc": True},
        AUDIO_OFFSET=0.0,
        AUDIO_CODEC="aac",
        AUDIO_BITRATE="256k",
    ):
        with patch("modules.runtime.pipeline.log_info") as mock_log:
            build_ffmpeg_cmd(
                Path("input.mp4"),
                Path("out_part.mkv"),
                atempo=1.0,
                fps=29.97,
                width=720,
                height=576,
                pixel_format="yuv420p10le",
            )

    logged = "\n".join(call.args[0] for call in mock_log.call_args_list if call.args)
    assert "AV1 path: NVIDIA GPU enabled" in logged


def test_build_ffmpeg_cmd_logs_cpu_fallback_for_av1():
    """AV1 SVT path should emit a clear CPU fallback log line."""
    pipeline = importlib.import_module("modules.runtime.pipeline")
    build_ffmpeg_cmd = getattr(pipeline, "_build_ffmpeg_cmd")

    with patch.multiple(
        "modules.runtime.pipeline",
        ENCODER="av1",
        HW_SETTINGS={"cpu_threads": 24, "has_av1_nvenc": False},
        AUDIO_OFFSET=0.0,
        AUDIO_CODEC="aac",
        AUDIO_BITRATE="256k",
    ):
        with patch("modules.runtime.pipeline.log_info") as mock_log:
            build_ffmpeg_cmd(
                Path("input.mp4"),
                Path("out_part.mkv"),
                atempo=1.0,
                fps=29.97,
                width=720,
                height=576,
                pixel_format="yuv420p10le",
            )

    logged = "\n".join(call.args[0] for call in mock_log.call_args_list if call.args)
    assert "AV1 path: CPU fallback enabled" in logged


def test_build_ffmpeg_cmd_av1_includes_audio_sync_filters():
    """Build AV1 command with atempo and adelay audio filters."""
    pipeline = importlib.import_module("modules.runtime.pipeline")
    build_ffmpeg_cmd = getattr(pipeline, "_build_ffmpeg_cmd")

    with patch.multiple(
        "modules.runtime.pipeline",
        ENCODER="av1",
        HW_SETTINGS={"cpu_threads": 32},
        AUDIO_OFFSET=1.25,
        AUDIO_CODEC="aac",
        AUDIO_BITRATE="256k",
    ):
        cmd = build_ffmpeg_cmd(
            Path("input.mp4"),
            Path("out_part.mkv"),
            atempo=1.01,
            fps=29.97,
            width=720,
            height=576,
            pixel_format="yuv420p10le",
        )

    cmd_str = " ".join(cmd)
    assert "atempo=1.010000" in cmd_str
    assert "adelay=1250|1250" in cmd_str


def test_build_ffmpeg_cmd_prores_uses_hw_thread_count():
    """Build ProRes command with thread count from detected hardware settings."""
    pipeline = importlib.import_module("modules.runtime.pipeline")
    build_ffmpeg_cmd = getattr(pipeline, "_build_ffmpeg_cmd")

    with patch("modules.runtime.pipeline.ENCODER", "prores"):
        with patch("modules.runtime.pipeline.HW_SETTINGS", {"cpu_threads": 24}):
            cmd = build_ffmpeg_cmd(
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
    """Run encoding pipeline with python-vspipe launcher and cleanup failure branch."""
    pipeline = importlib.import_module("modules.runtime.pipeline")
    run_encoding_pipeline = getattr(pipeline, "_run_encoding_pipeline")

    p_vspipe = MagicMock()
    p_vspipe.stdout = MagicMock()
    p_vspipe.stderr = MagicMock()
    p_vspipe.returncode = 0
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
                                    result = run_encoding_pipeline(
                                        ["python_exe", "-m", "modules.runtime.vspipe_native", "temp.vpy"],
                                        ["ffmpeg", "-i", "-"],
                                        100.0,
                                    )

    assert result is True


def test_run_encoding_pipeline_fails_when_vspipe_fails():
    """Success requires both FFmpeg and vspipe to exit cleanly."""
    pipeline = importlib.import_module("modules.runtime.pipeline")
    run_encoding_pipeline = getattr(pipeline, "_run_encoding_pipeline")

    p_vspipe = MagicMock()
    p_vspipe.stdout = MagicMock()
    p_vspipe.stderr = MagicMock()
    p_vspipe.returncode = 1
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

    with patch("subprocess.Popen", side_effect=[popen_vs, popen_ff]):
        with patch("modules.runtime.pipeline.get_vspipe_env", return_value={}):
            with patch("threading.Thread"):
                with patch("io.TextIOWrapper", return_value=[]):
                    with patch("modules.runtime.pipeline._finalize_encoding_success") as mock_finalize:
                        with patch("modules.runtime.pipeline._log_ffmpeg_failure") as mock_failure:
                            result = run_encoding_pipeline(
                                ["vspipe", "temp.vpy", "-"],
                                ["ffmpeg", "-i", "-"],
                                100.0,
                            )

    assert result is False
    mock_finalize.assert_not_called()
    mock_failure.assert_called_once_with(1, [])


def test_process_video_debug_venv_fallback_and_rename_failure():
    """Cover debug venv fallback and output rename failure error logging."""
    pipeline = importlib.import_module("modules.runtime.pipeline")

    input_path = Path("input.mp4")
    mock_stat = MagicMock()
    mock_stat.st_size = 5000
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


def test_resolve_vspipe_executable_uses_project_venv_when_path_lookup_fails():
    """Use the venv vspipe launcher when it is not exported onto PATH."""
    utils = importlib.import_module("modules.core.utils")
    with (
        patch("modules.core.utils.shutil.which", return_value=None),
        patch("modules.core.utils.resolve_venv_root", return_value="C:/repo/.VENV"),
        patch("modules.core.utils.os.path.isfile", return_value=True),
    ):
        vspipe = utils.resolve_vspipe_executable("C:/repo")

    expected_dir = "Scripts" if utils.os.name == "nt" else "bin"
    expected_name = "vspipe.exe" if utils.os.name == "nt" else "vspipe"
    assert vspipe.replace("\\", "/") == f"C:/repo/.VENV/{expected_dir}/{expected_name}"


def test_process_video_finalizes_only_after_successful_rename():
    """Emit final success only after the output rename succeeds."""
    pipeline = importlib.import_module("modules.runtime.pipeline")

    input_path = Path("input.mp4")
    call_order = []

    def record_rename(*_args, **_kwargs):
        call_order.append("rename")
        return True

    def record_finalize(*_args, **_kwargs):
        call_order.append("finalize")

    with patch.object(Path, "exists", side_effect=[True, True]):
        with patch("modules.runtime.pipeline._get_existing_output_result", return_value=None):
            with patch("modules.runtime.pipeline._build_processing_commands", return_value=(60.0, ["ffmpeg"], ["vspipe"])):
                with patch("modules.runtime.pipeline._run_encoding_pipeline", return_value=True):
                    with patch("modules.runtime.pipeline._rename_completed_output", side_effect=record_rename):
                        with patch("modules.runtime.pipeline._finalize_encoding_success", side_effect=record_finalize) as mock_finalize:
                            with patch("modules.runtime.pipeline.cleanup_temp_files"):
                                with patch("modules.runtime.pipeline.log_info"), patch("modules.runtime.pipeline.log_debug"):
                                    result = pipeline.process_video(input_path)

    assert result["status"] == "success"
    assert call_order == ["rename", "finalize"]
    mock_finalize.assert_called_once()


def test_process_video_skips_finalization_when_rename_fails():
    """Return failure without emitting final success when output rename fails."""
    pipeline = importlib.import_module("modules.runtime.pipeline")

    input_path = Path("input.mp4")

    with patch.object(Path, "exists", return_value=True):
        with patch("modules.runtime.pipeline._get_existing_output_result", return_value=None):
            with patch("modules.runtime.pipeline._build_processing_commands", return_value=(60.0, ["ffmpeg"], ["vspipe"])):
                with patch("modules.runtime.pipeline._run_encoding_pipeline", return_value=True):
                    with patch("modules.runtime.pipeline._rename_completed_output", return_value=False):
                        with patch("modules.runtime.pipeline._finalize_encoding_success") as mock_finalize:
                            with patch("modules.runtime.pipeline.cleanup_temp_files"):
                                with patch("modules.runtime.pipeline.log_info"), patch("modules.runtime.pipeline.log_debug"):
                                    result = pipeline.process_video(input_path)

    assert result["status"] == "failed"
    mock_finalize.assert_not_called()
