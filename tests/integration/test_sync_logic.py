"""Integration tests for drift correction and sync-guard behavior.

Audio is muxed after all segments are encoded, so the drift decision is
checked at the two seams that carry it: ``_calculate_audio_sync`` (the
decision) and ``_build_mux_cmd`` (where the ``atempo`` filter is applied).
"""

from pathlib import Path
from unittest.mock import patch

from modules.runtime import pipeline

# Module-private seams, bound the way the rest of the suite binds them.
_calculate_audio_sync = getattr(pipeline, "_calculate_audio_sync")
_build_mux_cmd = getattr(pipeline, "_build_mux_cmd")

DRIFT_CONFIG = {
    "auto_drift_correction": True,
    "audio_drift_min_seconds": 0.010,
    "audio_drift_max_percent": 1.5,
}


def _mux_cmd_for(audio_duration: float, video_duration: float, config: dict) -> str:
    """Return the mux command produced for a given audio/video duration pair."""
    with patch("modules.runtime.pipeline.get_duration", return_value=audio_duration):
        with patch("modules.runtime.pipeline.CONFIG", config):
            with patch("modules.runtime.pipeline.log_info"):
                atempo = _calculate_audio_sync(Path("test.mp4"), video_duration)
    with patch.multiple("modules.runtime.pipeline", AUDIO_OFFSET=0.0, AUDIO_CODEC="aac", AUDIO_BITRATE="320k"):
        return " ".join(_build_mux_cmd(Path("test.mp4"), Path("segments.txt"), Path("out_part.mov"), atempo))


def test_drift_logic_negligible():
    """Small drift (<0.010s) results in no atempo filter."""
    cmd_str = _mux_cmd_for(audio_duration=100.005, video_duration=100.0, config=DRIFT_CONFIG)
    assert "atempo" not in cmd_str
    assert "-c:v copy" in cmd_str


def test_drift_logic_negative_ignored():
    """Negative drift (audio shorter than video) is ignored."""
    cmd_str = _mux_cmd_for(audio_duration=100.0, video_duration=100.2, config=DRIFT_CONFIG)
    assert "atempo" not in cmd_str


def test_drift_logic_positive_correction():
    """Positive drift (audio longer than video) is corrected with atempo."""
    cmd_str = _mux_cmd_for(audio_duration=100.2, video_duration=100.0, config=DRIFT_CONFIG)
    assert "-af atempo=1.002000" in cmd_str
    assert "-map 1:a:0?" in cmd_str


def test_drift_guard_excessive():
    """Excessive drift (>1.5%) is ignored by the safety guard."""
    cmd_str = _mux_cmd_for(audio_duration=102.0, video_duration=100.0, config=DRIFT_CONFIG)
    assert "atempo" not in cmd_str


def test_drift_disabled():
    """Drift correction can be disabled via config."""
    cmd_str = _mux_cmd_for(audio_duration=100.5, video_duration=100.0, config={"auto_drift_correction": False})
    assert "atempo" not in cmd_str


def test_drift_zero_video_duration_is_safe():
    """A zero video duration never divides by zero and applies no correction."""
    with patch("modules.runtime.pipeline.get_duration", return_value=5.0):
        with patch("modules.runtime.pipeline.CONFIG", DRIFT_CONFIG):
            with patch("modules.runtime.pipeline.log_info"):
                assert _calculate_audio_sync(Path("test.mp4"), 0.0) == 1.0
