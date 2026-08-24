"""Runtime configuration loading and hardware profile detection."""

import ctypes
import os
import sys
from typing import NoReturn

import yaml

from modules.core.utils import get_nvidia_gpu_info, get_project_root, log_error, log_info

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


def _detect_ram_settings(settings):
    """Detects system RAM and updates cache settings."""
    try:
        kernel32 = ctypes.windll.kernel32

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
        if kernel32.GlobalMemoryStatusEx(ctypes.byref(meminfo)) == 0:
            log_info("  > RAM: Unknown (Cache: 4000 MB default)")
            return
        total_ram_gb = meminfo.ull_total_phys / (1024**3)

        settings["ram_cache_mb"] = _get_ram_cache_mb(total_ram_gb)
        log_info(f"  > RAM: {total_ram_gb:.1f} GB (Cache: {settings['ram_cache_mb']} MB)")
    except (AttributeError, OSError, ValueError):
        log_info("  > RAM: Unknown (Cache: 4000 MB default)")


def _detect_gpu_settings(settings):
    """Detects GPU presence and updates acceleration settings, prioritizing NVIDIA."""
    nvidia_index, gpu_name = get_nvidia_gpu_info()
    if nvidia_index is not None and gpu_name is not None:
        log_info(f"  > NVIDIA GPU Found (Index {nvidia_index}): {gpu_name}")
        settings["use_gpu_opencl"] = True
        settings["has_nvidia"] = True
        settings["has_av1_nvenc"] = True
        settings["gpu_device_index"] = nvidia_index
        if ENCODER == "av1":
            log_info("  > GPU Acceleration: ENABLED (OpenCL + NVENC)")
        else:
            log_info("  > GPU Acceleration: ENABLED (OpenCL for QTGMC)")
            log_info("    [NOTE] Encoder is set to CPU-bound profile (ProRes).")
            log_info("    Real-time speed may be limited by CPU.")
            log_info("           To use NVIDIA NVENC, set 'encoder: av1' in config.yaml.")
        return

    # Fallback if no NVIDIA or smi fails
    settings["has_nvidia"] = False
    settings["has_av1_nvenc"] = False
    settings["gpu_device_index"] = 0


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
