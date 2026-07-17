"""Integration tests for failure-path behavior in pipeline and vspipe utilities."""

import importlib
import io
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


def test_pipeline_interactive_input_interrupt():
    """Test KeyboardInterrupt in _get_interactive_input."""
    pipeline = importlib.import_module("modules.runtime.pipeline")

    with patch("builtins.input", side_effect=KeyboardInterrupt):
        get_interactive_input = getattr(pipeline, "_get_interactive_input")
        files = get_interactive_input({".mp4"})
        assert not files


def test_expand_input_path_filters_unsupported_and_processed_files():
    """Direct file inputs should use the same candidate-video filter as CLI paths."""
    pipeline = importlib.import_module("modules.runtime.pipeline")
    expand_input_path = getattr(pipeline, "_expand_input_path")

    supported_path = Path("clip.mp4")
    processed_path = Path("clip_deinterlaced.mp4")
    unsupported_path = Path("notes.txt")

    with patch.object(Path, "is_file", return_value=True):
        assert expand_input_path(supported_path, {".mp4"}) == [supported_path]
        assert expand_input_path(processed_path, {".mp4"}) == []
        assert expand_input_path(unsupported_path, {".mp4"}) == []


def test_pipeline_audio_sync_logic():
    """Test _calculate_audio_sync logic branches."""
    pipeline = importlib.import_module("modules.runtime.pipeline")
    calculate_audio_sync = getattr(pipeline, "_calculate_audio_sync")

    # 1. drift too large
    with patch("modules.runtime.pipeline.get_duration") as mock_dur:
        mock_dur.side_effect = lambda f, s=None: 100.0 if "a" in str(s) else 60.0
        val = calculate_audio_sync(Path("test.mp4"), 60.0)
        assert val == 1.0

    # 2. negative drift (audio shorter)
    with patch("modules.runtime.pipeline.get_duration") as mock_dur:
        mock_dur.side_effect = lambda f, s=None: 50.0
        with patch("modules.runtime.pipeline.log_info") as mock_log:
            val = calculate_audio_sync(Path("test.mp4"), 60.0)
            assert val == 1.0
            # Check log message content if possible, or just that it didn't crash
            assert mock_log.called


def test_utils_project_root_frozen():
    """Test get_project_root when frozen."""
    utils = importlib.import_module("modules.core.utils")

    with patch.object(sys, "frozen", True, create=True):
        with patch.object(sys, "executable", "/bin/exe"):
            assert utils.get_project_root() == "/bin"


def test_utils_parse_time_edge_cases():
    """Test parse_ffmpeg_time edge cases."""
    utils = importlib.import_module("modules.core.utils")

    assert utils.parse_ffmpeg_time(None) == (None, None, None)
    assert utils.parse_ffmpeg_time("invalid") == (None, None, None)


def test_utils_cleanup_error():
    """Test cleanup_temp_files unlink error."""
    utils = importlib.import_module("modules.core.utils")

    with patch("pathlib.Path.glob") as mock_glob:
        f = MagicMock()
        f.name = "test_intermediate.mkv"
        f.is_file.return_value = True
        f.unlink.side_effect = OSError("Access Denied")
        mock_glob.return_value = [f]

        # Should not raise
        utils.cleanup_temp_files(Path("."), "test")


def test_vspipe_log_errors():
    """Test vspipe logging errors."""
    vspipe = importlib.import_module("modules.runtime.vspipe")

    pipe = MagicMock()
    pipe.readline.side_effect = OSError("Read Error")
    vspipe.log_vspipe_output(pipe)


def test_entry_point_safety():
    """Try to import auto_deinterlancer without main execution."""
    auto_deinterlancer = importlib.import_module("auto_deinterlancer")

    assert hasattr(auto_deinterlancer, "main")


def test_pipeline_run_encoding_read_error():
    """Return false when encoding pipeline subprocess path reports failure."""
    pipeline = importlib.import_module("modules.runtime.pipeline")
    run_encoding_pipeline = getattr(pipeline, "_run_encoding_pipeline")

    vspipe_cmd = ["ls"]
    ffmpeg_cmd = ["ls"]

    with patch("subprocess.Popen") as mock_popen:
        p_vs = MagicMock()
        p_vs.stdout = MagicMock()

        p_ff = MagicMock()
        p_ff.stderr = io.BytesIO(b"bad")
        p_ff.wait.return_value = 1
        p_ff.returncode = 1

        mock_popen.side_effect = [p_vs, p_ff]

        with patch("modules.runtime.pipeline.get_vspipe_env", return_value={}):
            with patch("threading.Thread"):
                result = run_encoding_pipeline(vspipe_cmd, ffmpeg_cmd, 100)

    assert result is False


def test_vspipe_log_errors_specific():
    """Test vspipe logging specific exceptions."""
    vspipe = importlib.import_module("modules.runtime.vspipe")

    pipe = MagicMock()
    pipe.readline.side_effect = ValueError("Shutdown error")
    vspipe.log_vspipe_output(pipe)


def test_vspipe_parse_info_malformed():
    """Test _parse_vspipe_info_output with malformed data."""
    vspipe = importlib.import_module("modules.runtime.vspipe")
    parse_info_output = getattr(vspipe, "_parse_vspipe_info_output")

    t, _fps, _w, _h, _fmt = parse_info_output("Frames: garbage")
    assert t is None

    _t, _f, width, _height, _format_name = parse_info_output("Width: garbage")
    assert width is None

    _t, _f, _width, height, _format_name = parse_info_output("Height: garbage")
    assert height is None

    _t, _f, _width, _height, format_name = parse_info_output("Format Name:")
    assert format_name == ""


def test_vspipe_parse_info_fps_edge():
    """Test FPS parsing edge cases."""
    vspipe = importlib.import_module("modules.runtime.vspipe")
    parse_info_output = getattr(vspipe, "_parse_vspipe_info_output")

    _t, fps, _w, _h, _fmt = parse_info_output("FPS: garbage")
    assert fps is None
