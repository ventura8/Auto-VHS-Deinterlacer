import os
import sys
import yaml
import shutil
import subprocess
from modules.utils import log_info, log_error

# ==============================================================================
#  CONFIGURATION & HARDWARE
# ==============================================================================


def load_config():
    # Look for config in project root (parent of parent of this file)
    # this file: modules/config.py
    # parent: modules/
    # parent of parent: project_root/
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(base_dir, "config.yaml")

    if not os.path.exists(config_path):
        log_error(f"ERROR: Config file not found at {config_path}")
        sys.exit(1)

    with open(config_path, "r") as f:
        try:
            return yaml.safe_load(f)
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
AUDIO_OFFSET = float(CONFIG.get("audio_sync_offset", 0.0))
FIELD_ORDER = CONFIG.get("field_order", "tff").lower()
TV_STANDARD = CONFIG.get("tv_standard", "ntsc").lower()
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
        import ctypes
        kernel32 = ctypes.windll.kernel32

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        meminfo = MEMORYSTATUSEX()
        meminfo.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        kernel32.GlobalMemoryStatusEx(ctypes.byref(meminfo))
        total_ram_gb = meminfo.ullTotalPhys / (1024**3)

        settings["ram_cache_mb"] = _get_ram_cache_mb(total_ram_gb)
        log_info(f"  > RAM: {total_ram_gb:.1f} GB (Cache: {settings['ram_cache_mb']} MB)")
    except Exception:
        log_info("  > RAM: Unknown (Cache: 4000 MB default)")


def _detect_gpu_settings(settings):
    """Detects GPU presence and updates acceleration settings."""
    if shutil.which("nvidia-smi"):
        try:
            gpu_info = subprocess.check_output("nvidia-smi -L", shell=True).decode().strip()
            log_info(f"  > GPU Found: {gpu_info.split(':')[0]}")
            if "NVIDIA" in gpu_info:
                settings["use_gpu_opencl"] = True
                if ENCODER == "av1":
                    log_info("  > GPU Acceleration: ENABLED (OpenCL + NVENC)")
                else:
                    log_info("  > GPU Acceleration: ENABLED (OpenCL for QTGMC)")
                    log_info("    [NOTE] Encoder is set to CPU-bound profile (ProRes).")
                    log_info("    Real-time speed may be limited by CPU.")
                    log_info("           To use RTX 5090 NVENC, set 'encoder: av1' in config.yaml.")
        except Exception:
            pass


# HARDWARE DETECTION & OPTIMIZATION
def detect_hardware_settings():
    settings = {
        "tile_index": 0,
        "tile_x": 0,
        "tile_y": 0,  # Default: Full frame (ULTRA)
        "cpu_threads": os.cpu_count() or 16,
        "ram_cache_mb": 4000,  # Default safe value for low-RAM systems
        "use_gpu_opencl": True,  # Optimistic: Default to Hardware Acceleration
    }

    if PERF_PROFILE == "manual":
        manual = CONFIG.get("manual_settings", {})
        settings.update(manual)
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


HW_SETTINGS = detect_hardware_settings()


# Validate Encoder
VALID_ENCODERS = ["prores", "av1"]
if ENCODER not in VALID_ENCODERS:
    log_error(
        f"ERROR: Invalid encoder '{ENCODER}' in config. Must be one of: {VALID_ENCODERS}"
    )
    sys.exit(1)
