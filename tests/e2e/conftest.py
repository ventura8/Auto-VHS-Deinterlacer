"""Shared synthetic media generation and test configuration helpers for end-to-end testing."""

import contextlib
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from modules.core.utils import setup_environment

DEFAULT_TEST_CONFIG = {
    "deinterlace_mode": "QTGMC",
    "encoder": "prores",
    "tv_standard": "auto",
    "field_order": "tff",
    "audio_codec": "aac",
    "audio_bitrate": "320k",
    "auto_drift_correction": True,
    "audio_sync_offset": 0.0,
    "drift_guard_thresholds": {
        "max_drift_percent": 1.5,
        "min_drift_seconds": 0.010,
    },
    "qtgmc_settings": {
        "Preset": "Very Slow",
        "SourceMatch": 3,
        "Lossless": 2,
        "EZDenoise": 0.0,
        "NoiseProcess": 0,
        "Sharpness": 0.0,
    },
}


def check_media_binaries():
    """Verify presence of media binaries or trigger pytest skip."""
    setup_environment()
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        pytest.skip("ffmpeg or ffprobe not installed on test runner")

    candidate_dirs = [
        str(Path(".venv/bin").resolve()),
        str(Path(".venv/Scripts").resolve()),
        str(Path(".VENV/bin").resolve()),
        str(Path(".VENV/Scripts").resolve()),
    ]
    search_path = os.pathsep.join(candidate_dirs)
    if shutil.which("vspipe") is None and not shutil.which("vspipe", path=search_path):
        pytest.skip("vspipe not installed in system or venv")


def create_synthetic_stream(output_path: Path, width: int = 720, height: int = 480, fps: float = 29.97, field_order: str = "tff"):
    """Generate synthetic interlaced media with configurable dimensions and field parity."""
    tinterlace_mode = "interleave_top" if field_order == "tff" else "interleave_bottom"
    setfield_mode = "tff" if field_order == "tff" else "bff"

    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=duration=1:size={width}x{height}:rate={fps * 2}",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=1000:duration=1",
        "-vf",
        f"tinterlace=mode={tinterlace_mode},setfield={setfield_mode}",
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


def create_drift_stream(output_path: Path):
    """Generate synthetic test video with audio/video duration discrepancy."""
    args = [
        "ffmpeg",
        "-y",
        "-filter_complex",
        "testsrc=duration=2:size=720x480:rate=60,tinterlace=mode=interleave_top,setfield=tff[v];sine=f=1000:d=2.1[a]",
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-c:a",
        "aac",
        str(output_path),
    ]
    subprocess.check_call(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)


@contextlib.contextmanager
def temporary_config_override(overrides: dict):
    """Temporarily override config.yaml with custom settings for a test scenario."""
    config_path = Path("config.yaml")
    original_text = config_path.read_text(encoding="utf-8") if config_path.exists() else None
    merged = dict(DEFAULT_TEST_CONFIG)
    merged.update(overrides)
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(merged, f)
    try:
        yield
    finally:
        if original_text is not None:
            config_path.write_text(original_text, encoding="utf-8")
