"""Runtime configuration loading and hardware profile detection."""

import ctypes
import os
import sys
from typing import NoReturn

import yaml

from modules.core.utils import (
    get_nvidia_gpu_info,
    get_project_root,
    has_av1_nvenc_capability,
    log_error,
    log_info,
    vapoursynth_has_opencl_qtgmc,
)

# ==============================================================================
#  CONFIGURATION & HARDWARE
# ==============================================================================


def load_config():
    """Load configuration from config.yaml in the project root."""
    base_dir = get_project_root()
    config_path = os.path.join(base_dir, "config.yaml")

    if not os.path.exists(config_path):
        log_error(f"ERROR: Config file not found at {config_path}")
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        try:
            loaded = yaml.safe_load(f)
            return loaded if isinstance(loaded, dict) else {}
        except yaml.YAMLError as exc:
            log_error(f"ERROR loading config.yaml: {exc}")
            sys.exit(1)


CONFIG = load_config()


INPUT_FILE = CONFIG.get("input_file", r"C:\Videos\My_Capture.mp4")
OUTPUT_FILE = CONFIG.get("output_file", r"C:\Videos\Restored_Master.mp4")
DEINTERLACE_MODE = CONFIG.get("deinterlace_mode", "QTGMC")
ENCODER = CONFIG.get("encoder", "prores")
PERF_PROFILE = CONFIG.get("performance_profile", "auto")
AUDIO_CODEC = CONFIG.get("audio_codec", "aac")
AUDIO_BITRATE = CONFIG.get("audio_bitrate", "320k")
try:
    AUDIO_OFFSET = float(CONFIG.get("audio_sync_offset", 0.0))
except (TypeError, ValueError):
    log_error("ERROR: Invalid audio_sync_offset in config. Must be a number.")
    sys.exit(1)
_field_order_raw = CONFIG.get("field_order", "tff")
if not isinstance(_field_order_raw, str):
    log_error("ERROR: Invalid field_order in config. Must be a string.")
    sys.exit(1)
FIELD_ORDER = _field_order_raw.lower()

_tv_standard_raw = CONFIG.get("tv_standard", "ntsc")
if not isinstance(_tv_standard_raw, str):
    log_error("ERROR: Invalid tv_standard in config. Must be a string.")
    sys.exit(1)
TV_STANDARD = _tv_standard_raw.lower()
DEBUG_MODE = CONFIG.get("debug_logging", False)


def _get_ram_cache_mb(total_ram_gb):
    """Calculates RAM cache size based on total RAM."""
    if total_ram_gb > 48:
        # For 64GB+ systems (like Ryzen 9950X3D setups), use 50% RAM for Cache
        cache_mb = min(int(total_ram_gb * 0.50 * 1024), 48000)
        log_info("  > High-Performance RAM Profile Active (50% Allocation)")
    elif total_ram_gb > 24:
        # 32GB builds: Use 35%
        cache_mb = min(int(total_ram_gb * 0.35 * 1024), 16000)
    else:
        # Standard: 25%
        cache_mb = min(int(total_ram_gb * 0.25 * 1024), 8000)
    return max(cache_mb, 2000)


def _get_posix_sysconf_ram_gb() -> float | None:
    """Read physical RAM in GB via os.sysconf."""
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        size = os.sysconf("SC_PAGE_SIZE")
        if pages <= 0 or size <= 0:
            return None
        return (pages * size) / (1024**3)
    except (AttributeError, ValueError, OSError, TypeError):
        return None


def _parse_meminfo_line(line: str) -> float | None:
    """Parse MemTotal line from /proc/meminfo into GB."""
    if not line.startswith("MemTotal:"):
        return None
    parts = line.split()
    return (float(parts[1]) * 1024) / (1024**3) if len(parts) >= 2 else None


def _get_proc_meminfo_ram_gb() -> float | None:
    """Read physical RAM in GB via /proc/meminfo."""
    if not os.path.exists("/proc/meminfo"):
        return None
    try:
        with open("/proc/meminfo", "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                val = _parse_meminfo_line(line)
                if val is not None:
                    return val
    except (OSError, ValueError, IndexError):
        pass
    return None


def _get_posix_ram_gb() -> float | None:
    """Read total physical RAM in GB on POSIX systems (Linux/macOS)."""
    return _get_posix_sysconf_ram_gb() or _get_proc_meminfo_ram_gb()


def _get_windows_ram_gb() -> float | None:
    """Read total physical RAM in GB on Windows using GlobalMemoryStatusEx."""
    try:
        kernel32 = getattr(ctypes, "windll", None)
        if kernel32 is None or not hasattr(kernel32, "kernel32"):
            return None

        class _MemoryStatusEx(ctypes.Structure):
            """Windows memory status structure for GlobalMemoryStatusEx."""

            _fields_ = [
                ("dw_length", ctypes.c_ulong),
                ("dw_memory_load", ctypes.c_ulong),
                ("ull_total_phys", ctypes.c_ulonglong),
                ("ull_avail_phys", ctypes.c_ulonglong),
                ("ull_total_page_file", ctypes.c_ulonglong),
                ("ull_avail_page_file", ctypes.c_ulonglong),
                ("ull_total_virtual", ctypes.c_ulonglong),
                ("ull_avail_virtual", ctypes.c_ulonglong),
                ("ull_avail_extended_virtual", ctypes.c_ulonglong),
            ]

            def __init__(self):
                super().__init__()
                self.dw_length = ctypes.sizeof(type(self))

        meminfo = _MemoryStatusEx()
        if kernel32.kernel32.GlobalMemoryStatusEx(ctypes.byref(meminfo)) == 0:
            return None
        return meminfo.ull_total_phys / (1024**3)
    except (AttributeError, OSError, ValueError):
        return None


def _resolve_detected_ram_gb() -> float | None:
    """Resolve total system RAM across Windows and POSIX platforms."""
    if sys.platform == "win32" or hasattr(ctypes, "windll"):
        return _get_windows_ram_gb() or _get_posix_ram_gb()
    return _get_posix_ram_gb() or _get_windows_ram_gb()


def _detect_ram_settings(settings):
    """Detects system RAM and updates cache settings across all platforms."""
    total_ram_gb = _resolve_detected_ram_gb()
    if total_ram_gb is not None and total_ram_gb > 0:
        settings["ram_cache_mb"] = _get_ram_cache_mb(total_ram_gb)
        log_info(f"  > RAM: {total_ram_gb:.1f} GB (Cache: {settings['ram_cache_mb']} MB)")
    else:
        log_info(f"  > RAM: Unknown (Defaulting Cache to {settings['ram_cache_mb']} MB)")


def _log_opencl_qtgmc_enabled(*, nvenc_combo):
    """Log the QTGMC-on-OpenCL acceleration banner."""
    if nvenc_combo:
        log_info("  > GPU Acceleration: ENABLED (OpenCL for QTGMC + NVENC)")
        return
    log_info("  > GPU Acceleration: ENABLED (OpenCL for QTGMC)")
    if ENCODER != "prores":
        return
    log_info("    [NOTE] Encoder is set to CPU-bound profile (ProRes).")
    log_info("    Real-time speed may be limited by CPU.")
    log_info("           To use NVIDIA NVENC, set 'encoder: av1' in config.yaml.")


def _log_opencl_qtgmc_disabled(*, nvenc_only):
    """Log the banner when the QTGMC OpenCL interpolators are unavailable."""
    if nvenc_only:
        log_info("  > GPU Acceleration: NVENC encode only (QTGMC runs on CPU).")
    else:
        log_info("  > GPU Acceleration: DISABLED (QTGMC runs on CPU).")
    log_info("    [NOTE] The VapourSynth OpenCL QTGMC filter is unavailable or unstable;")
    log_info("           QTGMC will use its safe CPU implementation.")


def _log_av1_nvenc_fallback(*, has_nvidia, has_nvenc):
    """Explain why an AV1 request is using the CPU encoder."""
    if ENCODER != "av1" or has_nvenc:
        return
    if has_nvidia:
        log_info("    [NOTE] AV1 NVENC is unavailable on this NVIDIA/FFmpeg/driver stack;")
        log_info("           AV1 will use the CPU encoder (libsvtav1).")
        return
    log_info("    [NOTE] No NVIDIA AV1 NVENC device is available;")
    log_info("           AV1 will use the CPU encoder (libsvtav1).")


def _resolve_manual_opencl(settings):
    """Honour a manual ``use_gpu_opencl`` only when the OpenCL plugins are present."""
    if not settings.get("use_gpu_opencl", True):
        return False
    if vapoursynth_has_opencl_qtgmc(_qtgmc_requires_eedi3cl(), verify_runtime=True):
        return True
    log_info("  > [NOTE] manual_settings.use_gpu_opencl is true, but the VapourSynth OpenCL")
    log_info("           plugins are unavailable; QTGMC will run on CPU.")
    return False


def _report_qtgmc_acceleration(opencl_qtgmc, *, has_nvenc):
    """Log how QTGMC and the encoder will actually be accelerated."""
    nvenc_combo = ENCODER == "av1" and has_nvenc
    if opencl_qtgmc:
        _log_opencl_qtgmc_enabled(nvenc_combo=nvenc_combo)
    else:
        _log_opencl_qtgmc_disabled(nvenc_only=nvenc_combo)


def _detect_gpu_settings(settings):
    """Detects GPU presence and updates acceleration settings, prioritizing NVIDIA."""
    opencl_qtgmc = vapoursynth_has_opencl_qtgmc(_qtgmc_requires_eedi3cl(), verify_runtime=True)
    settings["use_gpu_opencl"] = opencl_qtgmc

    nvidia_index, gpu_name = get_nvidia_gpu_info()
    if nvidia_index is not None and gpu_name is not None:
        log_info(f"  > NVIDIA GPU Found (Index {nvidia_index}): {gpu_name}")
        settings["has_nvidia"] = True
        settings["has_av1_nvenc"] = has_av1_nvenc_capability()
        settings["gpu_device_index"] = nvidia_index
        _report_qtgmc_acceleration(opencl_qtgmc, has_nvenc=settings["has_av1_nvenc"])
        _log_av1_nvenc_fallback(has_nvidia=True, has_nvenc=settings["has_av1_nvenc"])
        return

    # Fallback if no NVIDIA or smi fails
    settings["has_nvidia"] = False
    settings["has_av1_nvenc"] = False
    settings["gpu_device_index"] = 0
    _report_qtgmc_acceleration(opencl_qtgmc, has_nvenc=False)
    _log_av1_nvenc_fallback(has_nvidia=False, has_nvenc=False)


def _qtgmc_requires_eedi3cl():
    """Return whether the configured QTGMC interpolation mode uses EEDI3CL."""
    qtgmc_settings = CONFIG.get("qtgmc_settings", {})
    edi_mode = qtgmc_settings.get("EdiMode", "nnedi3") if isinstance(qtgmc_settings, dict) else "nnedi3"
    return str(edi_mode).lower() in {"eedi3", "eedi3+nnedi3"}


def _reject_invalid_cpu_threads(message) -> NoReturn:
    """Abort configuration loading when cpu_threads is invalid."""
    log_error(message)
    sys.exit(1)


def _parse_cpu_threads_from_string(raw_value, detected_threads):
    """Parse cpu_threads from a string value."""
    stripped = raw_value.strip().lower()
    if stripped == "auto":
        return detected_threads

    try:
        return int(stripped)
    except ValueError:
        _reject_invalid_cpu_threads("ERROR: manual_settings.cpu_threads must be a positive integer or 'auto'.")


def _parse_cpu_threads_from_int(raw_value):
    """Parse cpu_threads from an integer value."""
    return raw_value


def _is_non_bool_int(raw_value):
    """Return True when raw_value is an int but not a bool."""
    return isinstance(raw_value, int) and not isinstance(raw_value, bool)


def _validate_cpu_threads(parsed):
    """Ensure cpu_threads is a positive integer."""
    if parsed < 1:
        _reject_invalid_cpu_threads("ERROR: manual_settings.cpu_threads must be >= 1.")
    return parsed


def _resolve_cpu_threads(raw_value):
    """Normalize cpu_threads from config into a valid positive integer."""
    detected_threads = os.cpu_count() or 16

    if isinstance(raw_value, str):
        return _validate_cpu_threads(_parse_cpu_threads_from_string(raw_value, detected_threads))

    if _is_non_bool_int(raw_value):
        return _validate_cpu_threads(_parse_cpu_threads_from_int(raw_value))

    _reject_invalid_cpu_threads("ERROR: manual_settings.cpu_threads must be a positive integer or 'auto'.")


def _reject_invalid_ram_cache_mb(message) -> NoReturn:
    """Abort configuration loading when ram_cache_mb is invalid."""
    log_error(message)
    sys.exit(1)


def _parse_ram_cache_mb_from_string(raw_value):
    """Parse ram_cache_mb from string."""
    try:
        return int(raw_value.strip())
    except ValueError:
        _reject_invalid_ram_cache_mb("ERROR: manual_settings.ram_cache_mb must be a positive integer.")


def _validate_ram_cache_mb(parsed):
    """Ensure ram_cache_mb is at least 128 MB."""
    if parsed < 128:
        _reject_invalid_ram_cache_mb("ERROR: manual_settings.ram_cache_mb must be >= 128 MB.")
    return parsed


def _resolve_ram_cache_mb(raw_value):
    """Normalize ram_cache_mb from config into a valid positive integer."""
    if isinstance(raw_value, str):
        return _validate_ram_cache_mb(_parse_ram_cache_mb_from_string(raw_value))

    if _is_non_bool_int(raw_value):
        return _validate_ram_cache_mb(raw_value)

    _reject_invalid_ram_cache_mb("ERROR: manual_settings.ram_cache_mb must be a positive integer.")


# HARDWARE DETECTION & OPTIMIZATION
def detect_hardware_settings():
    """Detect and build runtime hardware settings used by the pipeline."""
    settings = {
        "tile_index": 0,
        "tile_x": 0,
        "tile_y": 0,  # Default: Full frame (ULTRA)
        "cpu_threads": os.cpu_count() or 16,
        "ram_cache_mb": 4000,  # Default safe value for low-RAM systems
        "use_gpu_opencl": True,  # Optimistic: Default to Hardware Acceleration
        "has_nvidia": False,
        "has_av1_nvenc": False,
        "gpu_device_index": 0,  # Default device index
    }

    if PERF_PROFILE == "manual":
        manual = CONFIG.get("manual_settings", {})
        if not isinstance(manual, dict):
            log_error("ERROR: Invalid manual_settings in config. Must be a mapping.")
            sys.exit(1)
        settings.update(manual)
        settings["use_gpu_opencl"] = _resolve_manual_opencl(settings)
        settings["cpu_threads"] = _resolve_cpu_threads(settings.get("cpu_threads", "auto"))
        settings["ram_cache_mb"] = _resolve_ram_cache_mb(settings.get("ram_cache_mb", 4000))
        log_info("Processing Profile: MANUAL")
    else:
        # Auto-Detect
        log_info("Detecting Hardware...")

        # CPU
        settings["cpu_threads"] = os.cpu_count() or 16
        log_info(f"  > CPU Cores: {settings['cpu_threads']} threads (Ryzen/Intel)")

        # RAM Detection for Cache Sizing
        _detect_ram_settings(settings)

        # GPU - QTGMC doesn't strictly depend on CUDA for logic, but we log it anyway
        _detect_gpu_settings(settings)

        # QTGMC Profile: Always Archive
        log_info("  > Profile: Archival Grade (QTGMC)")

    return settings


def _load_hw_settings():
    """Load hardware settings with an opt-out for deterministic test runs."""
    if os.environ.get("AUTO_VHS_SKIP_HW_DETECT", "0") == "1":
        return {
            "tile_index": 0,
            "tile_x": 0,
            "tile_y": 0,
            "cpu_threads": os.cpu_count() or 16,
            "ram_cache_mb": 4000,
            "use_gpu_opencl": True,
            "has_nvidia": False,
            "has_av1_nvenc": False,
            "gpu_device_index": 0,
        }
    return detect_hardware_settings()


HW_SETTINGS = _load_hw_settings()


# Validate Encoder
VALID_ENCODERS = ["prores", "av1"]
if ENCODER not in VALID_ENCODERS:
    log_error(f"ERROR: Invalid encoder '{ENCODER}' in config. Must be one of: {VALID_ENCODERS}")
    sys.exit(1)


__all__ = [
    "load_config",
    "detect_hardware_settings",
    "CONFIG",
    "INPUT_FILE",
    "OUTPUT_FILE",
    "DEINTERLACE_MODE",
    "ENCODER",
    "PERF_PROFILE",
    "AUDIO_CODEC",
    "AUDIO_BITRATE",
    "AUDIO_OFFSET",
    "FIELD_ORDER",
    "TV_STANDARD",
    "DEBUG_MODE",
    "HW_SETTINGS",
    "VALID_ENCODERS",
    "os",
    "sys",
    "yaml",
]
