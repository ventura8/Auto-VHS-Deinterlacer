"""Complex pipeline flow tests for output naming and progress parsing."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from modules.core.config import CONFIG
from modules.runtime import pipeline


def _build_mock_processes():
    """Create context-managed Popen mocks for vspipe and ffmpeg."""
    p_vspipe = MagicMock()
    for attr_name in ("stdout", "stderr"):
        setattr(p_vspipe, attr_name, MagicMock())
    p_vspipe.returncode = 0
    p_vspipe.wait.return_value = None

    p_ffmpeg = MagicMock(returncode=0)
    p_ffmpeg.wait.return_value = None

    popen_vs = MagicMock()
    popen_vs.configure_mock(**{"__enter__.return_value": p_vspipe, "__exit__.return_value": False})

    popen_ff = MagicMock()
    popen_ff.configure_mock(**{"__enter__.return_value": p_ffmpeg, "__exit__.return_value": False})

    return p_vspipe, p_ffmpeg, popen_vs, popen_ff


def test_get_output_path_variations():
    """Test _get_output_path with different encoders."""
    input_p = Path("test.mp4")

    # helper to reset config

    # 1. ProRes
    with patch("modules.runtime.pipeline.ENCODER", "prores"):
        with patch.dict(CONFIG, {"output_suffix": "_prores"}):
            out = getattr(pipeline, "_get_output_path")(input_p)
            assert out.name == "test_prores.mov"

    # 2. AV1
    with patch("modules.runtime.pipeline.ENCODER", "av1"):
        with patch.dict(CONFIG, {"output_suffix_av1": "_av1"}):
            out = getattr(pipeline, "_get_output_path")(input_p)
            assert out.name == "test_av1.mkv"


def test_run_encoding_pipeline_progress_parsing():
    """Test _run_encoding_pipeline parsing of ffmpeg output."""
    vspipe_cmd = ["vspipe", "-", "-"]
    ffmpeg_cmd = ["ffmpeg", "-i", "-"]
    duration_sec = 100.0

    # Mock subprocess objects
    _p_vspipe, _p_ffmpeg, popen_vs, popen_ff = _build_mock_processes()

    # Simulate stderr lines from ffmpeg
    # We need to mock iteration over p_ffmpeg.stderr
    # pipeline.py uses: stderr_reader = io.TextIOWrapper(p_ffmpeg.stderr, ...)
    # But checking the code:
    #   if p_ffmpeg.stderr:
    #       stderr_reader = io.TextIOWrapper(p_ffmpeg.stderr...)
    # We can mock TextIOWrapper or just make p_ffmpeg.stderr iterable if we mock io.TextIOWrapper?
    # Easier: Mock io.TextIOWrapper

    lines = [
        "frame=  100 fps= 25 q=-1.0 size= 1024kB time=00:00:04.00 bitrate=2000.0kbits/s speed= 1.0x",
        "frame=  200 fps= 30 q=-1.0 size= 2048kB time=00:00:08.00 bitrate=2000.0kbits/s speed= 2.0x",
        "some other line",
        "frame=  300 fps= 30 q=-1.0 size= 3072kB time=00:00:12.00 bitrate=2000.0kbits/s speed=N/A",  # coverage for speed exceptions
    ]

    with patch("subprocess.Popen", side_effect=[popen_vs, popen_ff]):
        with patch("modules.runtime.pipeline.get_vspipe_env", return_value={}):
            with patch("threading.Thread"):
                with patch("io.TextIOWrapper", return_value=lines):  # Make it iterable
                    with patch("modules.runtime.pipeline.update_progress") as mock_update:
                        with patch("os.remove"):
                            with patch("pathlib.Path.exists", return_value=True):
                                ret = getattr(pipeline, "_run_encoding_pipeline")(
                                    vspipe_cmd,
                                    ffmpeg_cmd,
                                    duration_sec,
                                )
                                assert ret is True
                                assert mock_update.call_count >= 2
