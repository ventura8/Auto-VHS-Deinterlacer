"""End-to-End pipeline verification tests using real FFmpeg and VapourSynth dependencies."""

from pathlib import Path

import pytest

from modules.core.utils import get_duration, get_fps, probe_stream_entry
from modules.runtime.pipeline import process_video
from tests.e2e.conftest import check_media_binaries, create_synthetic_stream


def _verify_field_order(video_path: Path) -> str:
    """Return the field_order reported by ffprobe for the first video stream."""
    return probe_stream_entry(video_path, "field_order")


def _assert_success_output(out_file: Path):
    """Assert properties of success output video file."""
    assert out_file.exists()
    assert out_file.stat().st_size > 0
    assert get_fps(str(out_file)) > 50.0
    assert get_duration(str(out_file)) > 0.5


def _verify_pipeline_output(result: dict):
    """Verify result dictionary from process_video."""
    assert result["status"] == "success"
    _assert_success_output(result["output"])


@pytest.mark.e2e
@pytest.mark.real_deps
def test_real_pipeline_synthetic_deinterlace(tmp_path):
    """Test full pipeline execution with real synthesized interlaced media."""
    check_media_binaries()
    input_video = tmp_path / "synthetic_capture.mp4"
    create_synthetic_stream(input_video, width=720, height=480, fps=29.97, field_order="tff")

    assert input_video.exists()
    assert input_video.stat().st_size > 0
    assert get_duration(str(input_video)) > 0.5
    assert _verify_field_order(input_video) == "tt"

    result = process_video(input_video)
    _verify_pipeline_output(result)
