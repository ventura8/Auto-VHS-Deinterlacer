"""Shared synthetic media generation and test configuration helpers for end-to-end testing."""

import contextlib
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from modules.core.utils import probe_stream_entry, setup_environment

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


# seq_level_idx 19 is AV1 level 6.3, the highest the spec defines. Encoders that
# leave the level unset can stamp 7.x, which decoders such as libaom reject.
AV1_MAX_DEFINED_SEQ_LEVEL_IDX = 19


def _assert_every_frame_decodes(output_path: Path):
    """Decode the whole file, because a valid header can front a broken bitstream."""
    decode = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(output_path), "-f", "null", "-"],
        capture_output=True,
        check=False,
        timeout=180,
    )
    detail = decode.stderr.decode(errors="replace")[:500]
    assert decode.returncode == 0, f"decode failed: {detail}"
    assert not decode.stderr.strip(), f"decode emitted errors: {detail}"


def _assert_av1_level_is_defined(output_path: Path):
    """Reject AV1 levels the spec leaves undefined.

    FFmpeg decodes AV1 with dav1d, which accepts levels libaom refuses, so the
    decode pass above cannot catch this on its own.
    """
    level = probe_stream_entry(output_path, "level")
    assert level.lstrip("-").isdigit(), f"AV1 stream reported no usable level: {level!r}"
    assert int(level) <= AV1_MAX_DEFINED_SEQ_LEVEL_IDX, (
        f"AV1 seq_level_idx {level} exceeds the highest level the spec defines "
        f"({AV1_MAX_DEFINED_SEQ_LEVEL_IDX}); decoders such as libaom reject it"
    )


def assert_output_is_decodable(output_path: Path):
    """Assert every frame decodes and any AV1 stream advertises a usable level."""
    _assert_every_frame_decodes(output_path)
    if probe_stream_entry(output_path, "codec_name") == "av1":
        _assert_av1_level_is_defined(output_path)


def video_encoder_tag(output_path: Path) -> str:
    """Return the ENCODER tag FFmpeg wrote on the first video stream, e.g. "Lavc av1_nvenc".

    The tag names the encoder that actually produced the stream, so it tells a
    hardware encode from a CPU fallback even when the pipeline log is not shown.
    """
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream_tags=ENCODER",
            "-of",
            "default=nw=1:nk=1",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    return probe.stdout.strip()


def create_correctable_drift_stream(output_path: Path, video_seconds: int = 20, audio_extra: float = 0.08):
    """Generate a capture whose audio drift is large enough to correct but under the percentage guard.

    ``create_drift_stream`` produces 2s of video against 2.1s of audio, which is
    ~5% drift and is always rejected by the percentage guard, so it never reaches
    the atempo branch. The defaults here give 0.08s over 20s (0.4%), which clears
    ``audio_drift_min_seconds`` while staying inside ``audio_drift_max_percent``.
    """
    audio_seconds = video_seconds + audio_extra
    args = [
        "ffmpeg",
        "-y",
        "-filter_complex",
        (
            f"testsrc=duration={video_seconds}:size=720x480:rate=60,"
            f"tinterlace=mode=interleave_top,setfield=tff[v];"
            f"sine=f=1000:d={audio_seconds}[a]"
        ),
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
    subprocess.check_call(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180)


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
