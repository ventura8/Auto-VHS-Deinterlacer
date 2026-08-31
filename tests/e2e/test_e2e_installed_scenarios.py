"""Comprehensive End-to-End test suite for restoration scenarios against installed application."""

from pathlib import Path
from unittest.mock import patch

import pytest

from modules.core.utils import get_duration, get_fps, probe_stream_entry
from modules.runtime.pipeline import process_video
from tests.e2e.conftest import (
    check_media_binaries,
    create_drift_stream,
    create_synthetic_stream,
    temporary_config_override,
)


def _assert_video_properties(out_file: Path, min_fps: float, min_duration: float):
    """Verify video output file exists with expected fps and duration."""
    assert out_file.exists()
    assert out_file.stat().st_size > 0
    assert get_fps(str(out_file)) >= min_fps
    assert get_duration(str(out_file)) >= min_duration


@pytest.mark.e2e
@pytest.mark.real_deps
def test_scenario_ntsc_tff_restoration(tmp_path):
    """Scenario 2: Standard NTSC 29.97 fps (TFF) -> 59.94 fps bob deinterlace."""
    check_media_binaries()
    input_video = tmp_path / "ntsc_capture.mp4"
    create_synthetic_stream(input_video, width=720, height=480, fps=29.97, field_order="tff")

    result = process_video(input_video)
    assert result["status"] == "success"
    _assert_video_properties(result["output"], min_fps=59.0, min_duration=0.5)


@pytest.mark.e2e
@pytest.mark.real_deps
def test_scenario_pal_tff_restoration(tmp_path):
    """Scenario 3: Standard PAL 25.00 fps (TFF) -> 50.00 fps bob deinterlace."""
    check_media_binaries()
    input_video = tmp_path / "pal_capture.mp4"
    create_synthetic_stream(input_video, width=720, height=576, fps=25.00, field_order="tff")

    result = process_video(input_video)
    assert result["status"] == "success"
    _assert_video_properties(result["output"], min_fps=49.0, min_duration=0.5)


@pytest.mark.e2e
@pytest.mark.real_deps
def test_scenario_bff_restoration(tmp_path):
    """Scenario 4: Bottom-Field-First (BFF) legacy/DV-AVI capture."""
    check_media_binaries()
    input_video = tmp_path / "bff_capture.mp4"
    create_synthetic_stream(input_video, width=720, height=480, fps=29.97, field_order="bff")

    with temporary_config_override({"field_order": "bff"}):
        result = process_video(input_video)
        assert result["status"] == "success"
        _assert_video_properties(result["output"], min_fps=59.0, min_duration=0.5)


@pytest.mark.e2e
@pytest.mark.real_deps
def test_scenario_av_drift_correction(tmp_path):
    """Scenario 5: Audio-video drift correction for clock drift compensation."""
    check_media_binaries()
    input_video = tmp_path / "drift_capture.mp4"
    create_drift_stream(input_video)

    with temporary_config_override({"auto_drift_correction": True}):
        result = process_video(input_video)
        assert result["status"] == "success"
        _assert_video_properties(result["output"], min_fps=50.0, min_duration=1.5)


@pytest.mark.e2e
@pytest.mark.real_deps
def test_scenario_av1_encoder(tmp_path):
    """Scenario 7: High-efficiency AV1 output encoding mode."""
    check_media_binaries()
    input_video = tmp_path / "av1_capture.mp4"
    create_synthetic_stream(input_video, width=720, height=480, fps=29.97, field_order="tff")

    with temporary_config_override({"encoder": "av1"}):
        with patch("modules.runtime.pipeline.ENCODER", "av1"):
            result = process_video(input_video)
            assert result["status"] == "success"
            _assert_video_properties(result["output"], min_fps=59.0, min_duration=0.5)


@pytest.mark.e2e
@pytest.mark.real_deps
def test_scenario_flac_lossless_audio(tmp_path):
    """Scenario 9: Lossless FLAC audio codec preservation in MKV container."""
    check_media_binaries()
    input_video = tmp_path / "flac_capture.mp4"
    create_synthetic_stream(input_video, width=720, height=480, fps=29.97, field_order="tff")

    with temporary_config_override({"audio_codec": "flac", "encoder": "av1"}):
        with patch("modules.runtime.pipeline.AUDIO_CODEC", "flac"):
            with patch("modules.runtime.pipeline.ENCODER", "av1"):
                result = process_video(input_video)
                assert result["status"] == "success"
                assert result["output"].exists()
                audio_codec = probe_stream_entry(result["output"], "codec_name", stream_type="a")
                assert audio_codec == "flac"


@pytest.mark.e2e
@pytest.mark.real_deps
def test_scenario_corrupted_input_handling(tmp_path):
    """Scenario 10: Graceful failure handling on invalid/truncated media."""
    corrupted_file = tmp_path / "corrupted_file.mp4"
    corrupted_file.write_bytes(b"NOT_A_VALID_MEDIA_FILE_HEADER_GARBAGE")

    result = process_video(corrupted_file)
    assert result["status"] == "failed"
