"""Integration tests that cover branch behavior in pipeline helpers."""

import importlib
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
        with patch("modules.runtime.encoders.get_available_ffmpeg_encoders", return_value=frozenset({"libsvtav1"})):
            cmd = build_ffmpeg_cmd(
                Path("out_part.mkv"),
                fps=29.97,
                width=720,
                height=576,
                pixel_format="yuv420p10le",
            )

    cmd_str = " ".join(cmd)
    assert "-c:v libsvtav1" in cmd_str
    assert "-threads:v 32" in cmd_str
    assert "-an" in cmd
    assert "atempo" not in cmd_str


def _audio_filter_args(atempo):
    """Return the filter args for ``atempo`` with the configured offset neutralised."""
    pipeline = importlib.import_module("modules.runtime.pipeline")
    with patch("modules.runtime.pipeline.AUDIO_OFFSET", 0):
        return getattr(pipeline, "_get_audio_filter_args")(atempo)


def _atempo_tolerance():
    """Return the tolerance below which a correction is dropped."""
    return getattr(importlib.import_module("modules.runtime.pipeline"), "ATEMPO_NO_OP_TOLERANCE")


def test_audio_filter_args_skips_corrections_that_round_to_unity():
    """A correction smaller than the render precision is dropped rather than applied.

    "atempo=1.000000" is not a no-op in FFmpeg: the filter still resamples and
    trims a fixed ~1ms off the tail (measured identical at 5s and 30s inputs).
    Emitting no filter at all is what keeps such audio bit-exact.
    """
    tolerance = _atempo_tolerance()
    within = (1.0, 1.0 + tolerance / 2, 1.0 - tolerance / 2)

    assert [_audio_filter_args(value) for value in within] == [[], [], []]


def test_audio_filter_args_applies_corrections_above_tolerance():
    """A correction the render precision can express is passed to FFmpeg."""
    tolerance = _atempo_tolerance()

    assert _audio_filter_args(1.004) == ["-af", "atempo=1.004000"]
    assert _audio_filter_args(1.0 + tolerance * 10) == ["-af", "atempo=1.000010"]


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
            Path("out_part.mkv"),
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
        with patch("modules.runtime.encoders.log_info") as mock_log:
            build_ffmpeg_cmd(
                Path("out_part.mkv"),
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
        with patch("modules.runtime.encoders.log_info") as mock_log:
            build_ffmpeg_cmd(
                Path("out_part.mkv"),
                fps=29.97,
                width=720,
                height=576,
                pixel_format="yuv420p10le",
            )

    logged = "\n".join(call.args[0] for call in mock_log.call_args_list if call.args)
    assert "AV1 path: CPU fallback enabled" in logged


def test_build_mux_cmd_includes_audio_sync_filters():
    """The final mux copies video and applies atempo and adelay audio filters."""
    pipeline = importlib.import_module("modules.runtime.pipeline")
    build_mux_cmd = getattr(pipeline, "_build_mux_cmd")

    with patch.multiple(
        "modules.runtime.pipeline",
        ENCODER="av1",
        HW_SETTINGS={"cpu_threads": 32},
        AUDIO_OFFSET=1.25,
        AUDIO_CODEC="aac",
        AUDIO_BITRATE="256k",
    ):
        cmd = build_mux_cmd(Path("input.mp4"), Path("segments.txt"), Path("out_part.mkv"), atempo=1.01)

    cmd_str = " ".join(cmd)
    assert "-f concat -safe 0 -i segments.txt -i input.mp4 -map 0:v:0 -map 1:a:0? -c:v copy" in cmd_str
    assert "-af atempo=1.010000,adelay=1250|1250" in cmd_str
    assert "-c:a aac -b:a 256k out_part.mkv" in cmd_str


def test_build_ffmpeg_cmd_prores_uses_hw_thread_count():
    """Build ProRes command with thread count from detected hardware settings."""
    pipeline = importlib.import_module("modules.runtime.pipeline")
    build_ffmpeg_cmd = getattr(pipeline, "_build_ffmpeg_cmd")

    with patch("modules.runtime.pipeline.ENCODER", "prores"):
        with patch("modules.runtime.pipeline.HW_SETTINGS", {"cpu_threads": 24}):
            cmd = build_ffmpeg_cmd(
                Path("out_part.mov"),
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


def test_process_video_debug_venv_fallback_and_rename_failure(tmp_path):
    """Cover debug log level and output rename failure error logging."""
    pipeline = importlib.import_module("modules.runtime.pipeline")

    input_path = tmp_path / "input.mp4"
    input_path.write_bytes(b"x")
    job = {"duration_sec": 4.0}

    # Patch the logger's setLevel instead of reading the level back: process_video
    # mutates the shared "AutoVHS" logger, which would otherwise leak DEBUG into
    # every test that runs after this one.
    with patch.object(pipeline.logging.getLogger("AutoVHS"), "setLevel") as mock_set_level:
        with patch("modules.runtime.pipeline.DEBUG_MODE", True):
            with patch("modules.runtime.pipeline._build_processing_commands", return_value=job):
                with patch("modules.runtime.pipeline._run_resumable_encode", return_value=True):
                    with patch("pathlib.Path.replace", side_effect=OSError("rename failed")):
                        with patch("modules.runtime.pipeline.log_error") as mock_log_error:
                            with patch("modules.runtime.pipeline.log_info"):
                                result = pipeline.process_video(input_path)

    assert result["status"] == "failed"
    assert mock_log_error.called
    mock_set_level.assert_called_once_with(pipeline.logging.DEBUG)


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
            with patch("modules.runtime.pipeline._build_processing_commands", return_value={"duration_sec": 60.0}):
                with patch("modules.runtime.pipeline._run_resumable_encode", return_value=True):
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
            with patch("modules.runtime.pipeline._build_processing_commands", return_value={"duration_sec": 60.0}):
                with patch("modules.runtime.pipeline._run_resumable_encode", return_value=True):
                    with patch("modules.runtime.pipeline._rename_completed_output", return_value=False):
                        with patch("modules.runtime.pipeline._finalize_encoding_success") as mock_finalize:
                            with patch("modules.runtime.pipeline.cleanup_temp_files"):
                                with patch("modules.runtime.pipeline.log_info"), patch("modules.runtime.pipeline.log_debug"):
                                    result = pipeline.process_video(input_path)

    assert result["status"] == "failed"
    mock_finalize.assert_not_called()


def test_av1_cpu_encoder_prefers_svt_then_libaom():
    """The CPU fallback picks whichever AV1 encoder the active FFmpeg actually has."""
    encoders = importlib.import_module("modules.runtime.encoders")
    get_av1_cpu_encoder_args = encoders.get_av1_cpu_encoder_args

    both = frozenset({"libsvtav1", "libaom-av1"})
    with patch("modules.runtime.encoders.get_available_ffmpeg_encoders", return_value=both):
        assert get_av1_cpu_encoder_args()[1] == "libsvtav1"

    with patch("modules.runtime.encoders.get_available_ffmpeg_encoders", return_value=frozenset({"libaom-av1"})):
        libaom = get_av1_cpu_encoder_args()
    assert libaom[1] == "libaom-av1"
    # libaom needs an explicit target bitrate of 0 for constant-quality mode.
    assert "-b:v" in libaom
    assert libaom[libaom.index("-b:v") + 1] == "0"


def test_av1_cpu_encoder_falls_back_to_svt_when_listing_is_unavailable():
    """An unreadable encoder listing keeps the preferred encoder so FFmpeg reports it."""
    encoders = importlib.import_module("modules.runtime.encoders")
    get_av1_cpu_encoder_args = encoders.get_av1_cpu_encoder_args

    with patch("modules.runtime.encoders.get_available_ffmpeg_encoders", return_value=frozenset()):
        assert get_av1_cpu_encoder_args()[1] == "libsvtav1"


def test_av1_cpu_fallback_log_names_the_selected_encoder():
    """The log line reports the encoder that will actually run."""
    encoders = importlib.import_module("modules.runtime.encoders")

    with patch("modules.runtime.encoders.get_available_ffmpeg_encoders", return_value=frozenset({"libaom-av1"})):
        with patch("modules.runtime.encoders.log_info") as mock_log:
            encoders.log_encoder_execution_path("av1", {"has_av1_nvenc": False})

    logged = "\n".join(call.args[0] for call in mock_log.call_args_list if call.args)
    assert "CPU fallback enabled (libaom-av1)" in logged
