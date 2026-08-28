"""End-to-End pipeline verification tests using real FFmpeg and VapourSynth dependencies."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from modules.core.utils import get_duration, get_fps, probe_stream_entry, setup_environment
from modules.runtime.pipeline import process_video


def _has_required_binaries():
    """Return whether real ffmpeg and ffprobe are available in PATH."""
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _create_synthetic_interlaced_video(output_path: Path, duration_sec: int = 1, fps: float = 29.97):
    """Generate a real interlaced video with test tone using ffmpeg."""
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=duration={duration_sec}:size=720x480:rate={fps * 2}",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=1000:duration={duration_sec}",
        # setfield=tff tags top-field-first; FFmpeg 9 removed the "-top" output option.
        "-vf",
        "tinterlace=mode=interleave_top,setfield=tff",
        "-flags",
        "+ildct+ilme",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        str(output_path),
    ]
    subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)


def _verify_field_order(video_path: Path) -> str:
    """Return the field_order reported by ffprobe for the first video stream."""
    return probe_stream_entry(video_path, "field_order")


def _check_binaries_or_skip():
    """Verify presence of media binaries or trigger pytest skip."""
    setup_environment()
    if not _has_required_binaries():
        pytest.skip("ffmpeg or ffprobe not installed on test runner")

    if shutil.which("vspipe") is None:
        candidate_dirs = [
            str(Path(".venv/bin").resolve()),
            str(Path(".venv/Scripts").resolve()),
            str(Path(".VENV/bin").resolve()),
            str(Path(".VENV/Scripts").resolve()),
        ]
        search_path = os.pathsep.join(candidate_dirs)
        venv_vspipe = shutil.which("vspipe", path=search_path)
        if not venv_vspipe:
            pytest.skip("vspipe not installed in system or venv")


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
    _check_binaries_or_skip()
    input_video = tmp_path / "synthetic_capture.mp4"
    _create_synthetic_interlaced_video(input_video, duration_sec=1, fps=29.97)

    assert input_video.exists()
    assert input_video.stat().st_size > 0
    assert get_duration(str(input_video)) > 0.5
    assert _verify_field_order(input_video) == "tt"

    result = process_video(input_video)
    _verify_pipeline_output(result)
