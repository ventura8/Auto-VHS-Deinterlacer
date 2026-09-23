"""FFmpeg video-encoder argument selection.

Kept separate from the pipeline orchestration so the encoder choice, which is
also part of the resume fingerprint, has one home and one set of tests.
"""

from modules.core.utils import get_available_ffmpeg_encoders, log_info

# AV1 CPU encoders in preference order. SVT-AV1 is the fastest good-quality
# option; libaom is the one most builds carry when SVT-AV1 is absent.
AV1_CPU_ENCODERS = (
    ("libsvtav1", ("-c:v", "libsvtav1", "-preset", "6", "-crf", "22", "-pix_fmt", "yuv420p10le")),
    ("libaom-av1", ("-c:v", "libaom-av1", "-cpu-used", "5", "-crf", "22", "-b:v", "0", "-pix_fmt", "yuv420p10le")),
)

PRORES_ARGS = ("-c:v", "prores_ks", "-profile:v", "3", "-vendor", "apl0", "-bits_per_mb", "8000", "-pix_fmt", "yuv422p10le")
# The level must be pinned. Left to itself av1_nvenc stamps seq_level_idx 23
# (level 7.3) into the sequence header even for a 720x480 source, and the AV1
# spec does not define the 7.x levels, so libaom refuses the bitstream outright
# ("Value 23 of seq_level_idx[0] is not yet defined") while dav1d accepts it.
# 5.1 is a mainstream tier that covers anything up to 4K60, far above the SD
# captures this pipeline produces.
AV1_NVENC_LEVEL = "5.1"
AV1_NVENC_ARGS = (
    "-c:v",
    "av1_nvenc",
    "-preset",
    "p5",
    "-cq",
    "22",
    "-b:v",
    "0",
    "-level",
    AV1_NVENC_LEVEL,
    "-pix_fmt",
    "p010le",
)


def get_av1_cpu_encoder_args() -> list[str]:
    """Return arguments for the first AV1 CPU encoder this FFmpeg actually has.

    SVT-AV1 is preferred, but several common builds ship libaom instead (the
    Windows "essentials" build is one), so hard-coding ``libsvtav1`` made the
    CPU fallback fail outright on them. When neither is listed the SVT
    arguments are returned unchanged so FFmpeg reports the missing encoder.
    """
    available = get_available_ffmpeg_encoders()
    for name, args in AV1_CPU_ENCODERS:
        if name in available:
            return list(args)
    return list(AV1_CPU_ENCODERS[0][1])


def get_video_encoder_args(encoder: str, hardware_settings: dict) -> list[str]:
    """Return the FFmpeg video encoder argument list for the configured encoder."""
    if encoder == "prores":
        return list(PRORES_ARGS)
    if hardware_settings.get("has_av1_nvenc", False):
        return list(AV1_NVENC_ARGS)
    return get_av1_cpu_encoder_args()


def log_encoder_execution_path(encoder: str, hardware_settings: dict):
    """Log whether the active video encoder path is GPU or CPU based."""
    if encoder == "av1":
        if hardware_settings.get("has_av1_nvenc", False):
            log_info("   [ENCODER] AV1 path: NVIDIA GPU enabled (av1_nvenc).")
            return
        cpu_encoder = get_av1_cpu_encoder_args()[1]
        log_info(f"   [ENCODER] AV1 path: CPU fallback enabled ({cpu_encoder}).")
        return

    log_info("   [ENCODER] ProRes path: CPU encoder enabled (prores_ks).")


__all__ = [
    "AV1_CPU_ENCODERS",
    "AV1_NVENC_LEVEL",
    "get_av1_cpu_encoder_args",
    "get_video_encoder_args",
    "log_encoder_execution_path",
]
