import os
import sys
import subprocess
import shutil
import signal
import atexit
import yaml
from typing import List

# ==============================================================================
#  AUTO-VHS-DEINTERLACER
#  Deinterlancing & Auto-Sync Pipeline
# ==============================================================================


import time
import platform
from pathlib import Path
import threading
import logging

# Configure Logging - always write to project root
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
log_file = os.path.join(SCRIPT_DIR, "auto_vhs.log")
logger = logging.getLogger("AutoVHS")
logger.setLevel(logging.DEBUG)

# File Handler (DEBUG level -> auto_vhs.log in project root)
# File Handler (DEBUG level -> auto_vhs.log in project root)
file_handler = logging.FileHandler(log_file, mode='w', encoding='utf-8')
file_handler.setLevel(logging.DEBUG)


class ISOFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        from datetime import datetime
        dt = datetime.fromtimestamp(record.created).astimezone()
        return dt.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + dt.strftime('%z')


file_formatter = ISOFormatter('%(asctime)s [%(levelname)s] %(message)s')
file_handler.setFormatter(file_formatter)

# Console Handler (INFO level -> minimal output)
# We write to stderr to avoid interfering with any potential pipe usage
console_handler = logging.StreamHandler(sys.stderr)
console_handler.setLevel(logging.INFO)
console_formatter = logging.Formatter('%(message)s')  # Clean format for user
console_handler.setFormatter(console_formatter)

logger.addHandler(file_handler)
logger.addHandler(console_handler)


def log_debug(msg):
    try:
        logger.debug(msg)
        for handler in logger.handlers:
            try:
                handler.flush()
            except (ValueError, RuntimeError, AttributeError):
                pass
    except (ValueError, RuntimeError, AttributeError):
        pass


def log_info(msg):
    try:
        logger.info(msg)
        for handler in logger.handlers:
            try:
                handler.flush()
            except (ValueError, RuntimeError, AttributeError):
                pass
    except (ValueError, RuntimeError, AttributeError):
        pass


def log_error(msg):
    try:
        logger.error(msg)
        for handler in logger.handlers:
            try:
                handler.flush()
            except (ValueError, RuntimeError, AttributeError):
                pass
    except (ValueError, RuntimeError, AttributeError):
        pass


# Process Tracking & Signal Handling
ACTIVE_PROCS: List[subprocess.Popen] = []


def cleanup_on_exit(signum=None, frame=None):
    """Terminates all registered subprocesses and exits."""
    if signum:
        sig_name = signal.Signals(signum).name
        log_debug(f"[SYSTEM] Received signal {sig_name}. Shutting down...")

    for p in ACTIVE_PROCS:
        if p.poll() is None:
            try:
                log_debug(f"[SYSTEM] Terminating process {p.pid}...")
                p.terminate()
                # Give it a moment to die gracefully, then kill if needed
                time.sleep(0.1)
                if p.poll() is None:
                    p.kill()
            except Exception:
                pass

    # Clean exit if we are in a signal handler
    if signum:
        sys.exit(1)


# Register cleanup for normal exits and various signals
atexit.register(cleanup_on_exit)
signal.signal(signal.SIGINT, cleanup_on_exit)
signal.signal(signal.SIGTERM, cleanup_on_exit)
if platform.system() == "Windows":
    # SIGBREAK is sent when the console window is closed on Windows
    sigbreak = getattr(signal, "SIGBREAK", None)
    if sigbreak is not None:
        signal.signal(sigbreak, cleanup_on_exit)


def run_command(args, **kwargs):
    """Executes a command and tracks it for cleanup."""
    p = subprocess.Popen(args, **kwargs)
    ACTIVE_PROCS.append(p)
    try:
        p.wait()
        return p
    finally:
        if p in ACTIVE_PROCS:
            ACTIVE_PROCS.remove(p)


def log_vspipe_output(pipe):
    """Monitors vspipe stderr for errors and progress."""
    try:
        # Use a sentinel that works for both bytes and strings
        for line in iter(pipe.readline, b''):
            if not line:
                break
            if isinstance(line, bytes):
                line_str = line.decode('utf-8', errors='replace').strip()
            else:
                line_str = line.strip()

            if line_str:
                # Log ALL vspipe output to file for debugging
                log_debug(f"[VSPIPE] {line_str}")
                # Also log errors explicitly
                if any(x in line_str for x in ["Script execution failed", "Error", "Failed"]):
                    log_error(f"[VSPIPE ERROR] {line_str}")
    except (ValueError, RuntimeError, AttributeError):
        # Handle cases where logging fails during interpreter shutdown
        pass
    except Exception:
        pass


def setup_environment():
    """Setup FFmpeg and VapourSynth paths from local venv."""
    try:
        # Determine venv root relative to this script or current python
        if getattr(sys, 'frozen', False):
            # If running as executable
            base_dir = os.path.dirname(sys.executable)
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))

        venv_root = os.path.join(base_dir, ".venv")
        if not os.path.exists(venv_root):
            # Fallback to checking parent of sys.executable if .venv not found in script dir
            venv_root = os.path.dirname(os.path.dirname(sys.executable))

        # 1. FFmpeg
        # Check "Scripts" (Windows) or "bin" (Linux/Unix)
        venv_scripts = os.path.join(venv_root, "Scripts")
        if not os.path.exists(venv_scripts):
            venv_scripts = os.path.join(venv_root, "bin")

        if os.path.exists(venv_scripts):
            os.environ["PATH"] = venv_scripts + os.pathsep + os.environ["PATH"]

        # 2. VapourSynth Portable
        venv_vs = os.path.join(venv_root, "vs")
        if os.path.exists(venv_vs):
            # Add VS to PATH so vspipe can load its DLLs
            os.environ["PATH"] = venv_vs + os.pathsep + os.environ["PATH"]

            # Windows: Ensure DLLs are findable by Python 3.8+
            if platform.system() == "Windows" and hasattr(os, "add_dll_directory"):
                try:
                    os.add_dll_directory(venv_vs)
                except Exception:
                    pass

            # Set plugin path for VapourSynth plugin autoloading
            # [FIX] Check both standard 'plugins' and legacy 'vs-plugins'
            vs_plugins = os.path.join(venv_vs, "plugins")
            if not os.path.exists(vs_plugins):
                vs_plugins = os.path.join(venv_vs, "vs-plugins")

            if os.path.exists(vs_plugins):
                os.environ["VAPOURSYNTH_PLUGIN_PATH"] = vs_plugins
    except Exception:
        pass


# Call immediately
setup_environment()

# Windows specific
try:
    import winreg
except ImportError:
    pass

# ==============================================================================
#  AUTO-VHS-DEINTERLACER
#  Deinterlancing & Auto-Sync Pipeline
# ==============================================================================


# LOAD CONFIGURATION
# ------------------------------------------------------------------------------
def load_config():
    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
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


# HARDWARE DETECTION & OPTIMIZATION
# ------------------------------------------------------------------------------
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
            # High-end Workstation Optimization (>32GB RAM)
            if total_ram_gb > 48:
                # For 64GB+ systems (like Ryzen 9950X3D setups), use 50% RAM for Cache
                # This prevents "underusing" available memory during heavy QTGMC calls
                cache_mb = min(int(total_ram_gb * 0.50 * 1024), 48000)
                log_info("  > High-Performance RAM Profile Active (50% Allocation)")
            elif total_ram_gb > 24:
                # 32GB builds: Use 35%
                cache_mb = min(int(total_ram_gb * 0.35 * 1024), 16000)
            else:
                # Standard: 25%
                cache_mb = min(int(total_ram_gb * 0.25 * 1024), 8000)

            settings["ram_cache_mb"] = max(cache_mb, 2000)
            log_info(f"  > RAM: {total_ram_gb:.1f} GB (Cache: {settings['ram_cache_mb']} MB)")
        except Exception:
            log_info("  > RAM: Unknown (Cache: 4000 MB default)")

        # GPU - QTGMC doesn't strictly depend on CUDA for logic, but we log it anyway
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
                        log_info("    [NOTE] Encoder is set to CPU-bound profile (ProRes). Real-time speed may be limited by CPU.")
                        log_info("           To use RTX 5090 NVENC, set 'encoder: av1' in config.yaml.")
            except Exception:
                pass

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


# ==============================================================================
# SYSTEM CHECKS
# ==============================================================================
def check_requirements():
    """Ensures VapourSynth and FFmpeg are accessible."""
    tools = ["ffmpeg", "ffprobe", "vspipe"]
    missing = []
    for tool in tools:
        if shutil.which(tool) is None:
            missing.append(tool)

    if missing:
        log_error(
            f"CRITICAL ERROR: The following tools are not in your SYSTEM PATH: {', '.join(missing)}"
        )
        log_error("Please install VapourSynth and FFmpeg and add them to your PATH.")
        sys.exit(1)


# ==============================================================================
# VAPOURSYNTH SCRIPT GENERATOR
# ==============================================================================
def create_vpy_script(input_file, output_script, mode, override_settings=None):
    """Generates a VapourSynth script based on the selected mode."""
    current_settings = override_settings if override_settings else HW_SETTINGS

    # 1. Path handling
    safe_input = os.path.abspath(input_file).replace("\\", "/").strip()
    current_root = os.getcwd().replace("\\", "/").strip()
    venv_root = os.path.dirname(os.path.dirname(sys.executable)).replace("\\", "/").strip()

    # Identify site-packages
    site_paths = []
    for p in sys.path:
        if "site-packages" in p and "venv" in p:
            site_paths.append(p.replace("\\", "/").strip())

    portable_site_pkgs = f"{venv_root}/vs/Lib/site-packages"
    portable_root = f"{venv_root}/vs"
    if portable_site_pkgs not in site_paths:
        site_paths.append(portable_site_pkgs)
    if portable_root not in site_paths:
        site_paths.append(portable_root)

    # 2. Build lines
    lines = []
    lines.append("import sys")
    lines.append(f"sys.path.insert(0, r'{current_root}')")
    for p in site_paths:
        lines.append(f"sys.path.append(r'{p}')")

    mvs_path = f"{current_root}/mvsfunc"
    if os.path.exists(mvs_path):
        lines.append(f"sys.path.append(r'{mvs_path}')")

    lines.append("import vapoursynth as vs")
    lines.append("import havsfunc as haf")
    lines.append("core = vs.core")
    lines.append(f"core.num_threads = {current_settings['cpu_threads']}")
    lines.append(f"core.max_cache_size = {current_settings['ram_cache_mb']}")
    lines.append("")

    # 3. Essential Plugins (Defensive loading)
    # [FIX] Search in both standard 'plugins' and legacy 'vs-plugins'
    plugin_dir = os.path.join(venv_root, "vs", "plugins")
    if not os.path.exists(plugin_dir):
        plugin_dir = os.path.join(venv_root, "vs", "vs-plugins")

    essential = [
        "ffms2.dll", "libmvtools.dll", "libnnedi3.dll", "NNEDI3CL.dll", "LSMASHSource.dll",
        "neo-fft3d.dll", "RemoveGrainVS.dll", "fmtconv.dll", "MiscFilters.dll",
        "EEDI3.dll", "EEDI3m.dll"
    ]
    plugin_lines = []

    # Also load coreplugins explicitly if present
    core_plugin_dir = os.path.join(venv_root, "vs", "coreplugins")
    if os.path.exists(core_plugin_dir):
        avs_compat = os.path.join(core_plugin_dir, "AvsCompat.dll")
        if os.path.exists(avs_compat):
            avs_compat_path = avs_compat.replace('\\', '/')
            plugin_lines.append(f"try: core.std.LoadPlugin(r'{avs_compat_path}')\nexcept: pass")

    for p_name in essential:
        p_path = os.path.join(plugin_dir, p_name).replace("\\", "/")
        if os.path.exists(p_path):
            plugin_lines.append(f"""
try:
    core.std.LoadPlugin(r'{p_path}')
except Exception as e:
    msg = str(e)
    if 'already loaded' not in msg.lower():
        sys.stderr.write(f'Failed to load {p_name}: {{msg}}\\n')
""")

    plugin_block = "\n".join(plugin_lines)
    lines.append(plugin_block)

    # [FIX] Legacy havsfunc expects 'eedi3m' namespace, modern plugin uses 'eedi3'
    lines.append("if hasattr(core, 'eedi3') and not hasattr(core, 'eedi3m'):")
    lines.append("    core.eedi3m = core.eedi3")

    lines.append("")
    # [SYNC FIX] Determine Standard FPS
    fps_num = 30000
    fps_den = 1001

    fps_logic = TV_STANDARD
    if fps_logic == "auto":
        detected_fps = get_fps(safe_input)
        if abs(detected_fps - 25.0) < 0.5:
            fps_logic = "pal"
        else:
            fps_logic = "ntsc"

    if fps_logic == "pal":
        fps_num, fps_den = 25, 1
    else:
        fps_num, fps_den = 30000, 1001

    # [LOADER] Use FFMS2 with internal FPS conversion (fpsnum/fpsden)
    # This forces the loader to provide a constant frame rate by duplicating frames
    # where timestamps were missing in the source. This is the key to fixing
    # progressive sync drift and duration shortening on VHS captures.
    lines.append(f"clip = core.ffms2.Source(r'{safe_input}', fpsnum={fps_num}, fpsden={fps_den})")

    lines.append("clip = core.resize.Point(clip, format=vs.YUV420P16)")
    lines.append("")

    qtgmc_params = CONFIG.get("qtgmc_settings", {})

    # GPU Optimizations
    qtgmc_args = {
        "Preset": qtgmc_params.get("Preset", "Very Slow"),
        "InputType": 0,
        "TFF": (True if FIELD_ORDER == "tff" else False),
        "SourceMatch": qtgmc_params.get("SourceMatch", 3),
        "Lossless": qtgmc_params.get("Lossless", 2),
        "TR2": 3,
        "EZDenoise": qtgmc_params.get("EZDenoise", 0.0),
        "NoiseProcess": qtgmc_params.get("NoiseProcess", 0),
        "Sharpness": qtgmc_params.get("Sharpness", 0.0),
        "FPSDivisor": 1,
    }

    if current_settings["use_gpu_opencl"]:
        # Enable NNEDI3CL (OpenCL) -> Huge speedup for Preset="Very Slow"
        qtgmc_args["EdiMode"] = "NNEDI3CL"
        # qtgmc_args["NNEDI3"] = 2  # Incorrect arg, removed

    lines.append("clip = haf.QTGMC(clip, **" + str(qtgmc_args) + ")")
    lines.append("")
    lines.append("clip.set_output()")

    # 4. Binary Write
    log_debug(f"[DEBUG] Generating VPY for: {safe_input}")
    output_content = "\n".join(lines)
    with open(output_script, "wb") as f:
        f.write(output_content.encode("utf-8"))
        f.write(b"\n")

    log_debug(f"[DEBUG] VPY saved to: {output_script} (Size: {os.path.getsize(output_script)})")


# ==============================================================================
# UI & HELPERS
# ==============================================================================

def parse_ffmpeg_time(line_str):
    """
    Extracts time in seconds, timestamp string, and speed from FFmpeg output.
    Returns: (seconds_float, time_str, speed_str)
    """
    if not line_str:
        return None, None, None
    import re

    # Match time=HH:MM:SS.ms (optional milliseconds)
    time_match = re.search(r"time=(\d{2}:\d{2}:\d{2}(?:\.\d+)?)", line_str)
    # Match speed=...x (e.g. speed=0.98x or speed= 1.2x)
    speed_match = re.search(r"speed=\s*(\d+\.?\d*x)", line_str)

    seconds = None
    time_s = None
    speed_s = None

    if time_match:
        time_s = time_match.group(1)
        try:
            parts = time_s.split(":")
            h = float(parts[0])
            m = float(parts[1])
            s = float(parts[2])
            seconds = h * 3600 + m * 60 + s
        except ValueError:
            seconds = None

    if speed_match:
        speed_s = speed_match.group(1)

    return seconds, time_s, speed_s


def cleanup_temp_files(work_dir, stem):
    """Robust cleanup of all temporary files."""
    patterns = [
        f"{stem}_temp_script.vpy",
        f"{stem}_intermediate.mov",
        f"{stem}_intermediate.mkv",
        f"{stem}.*ffindex",  # Clean FFMS2 index files
        f"{stem}.*lwi",     # Clean LSMASH index files
        "*.vpy",  # Safety: Clean stray VPYs
    ]

    # Be careful with wildcards, only delete if confident
    for p_str in patterns:
        for f in work_dir.glob(p_str):
            # Only delete if it looks like a temp file we created
            if f.is_file() and ("temp" in f.name or "intermediate" in f.name or "ffindex" in f.name or "lwi" in f.name):
                try:
                    f.unlink()
                except Exception:
                    pass


def update_progress(percent, message, time_str=None, speed_str=None, eta_str=None):
    """Draws a unified progress bar with optional stats."""
    bar_length = 30
    filled_length = int(bar_length * percent // 100)
    bar = "█" * filled_length + "-" * (bar_length - filled_length)

    details = f"{percent:.2f}%"
    if time_str:
        details += f" | {time_str}"
    if speed_str:
        details += f" | {speed_str}"
    if eta_str:
        details += f" | ETA: {eta_str}"

    sys.stderr.write(f"\r[{bar}] {details} | {message}")
    sys.stderr.flush()


def get_cpu_name():
    try:
        key_path = r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path)
        processor_name = winreg.QueryValueEx(key, "ProcessorNameString")[0]
        return processor_name.strip()
    except Exception:
        return platform.processor()


def get_gpu_name():
    try:
        output = subprocess.check_output("nvidia-smi -L", shell=True).decode()
        if "NVIDIA" in output:
            return output.split(":")[1].split("(")[0].strip()
    except Exception:
        pass
    return "Generic / Not Detected"


def _show_banner(cpu, gpu):
    log_info("\n" + "=" * 60)
    log_info("   AUTO-VHS-DEINTERLACER (STUDIO REFERENCE) - v1.1.0 (Hardware Optimized)")
    log_info(f"   Running on: {platform.system()} {platform.release()}")
    log_info("=" * 60)

    log_info("\n[HARDWARE DETECTED]")
    log_info(f"   CPU : {cpu}")
    log_info(f"   GPU : {gpu}")

    log_info(f"\n[AUTO-TUNED SETTINGS -> Profile: {PERF_PROFILE.upper()}]")
    log_info(f"   Mode        : {DEINTERLACE_MODE}")
    log_info(f"   Encoder     : {ENCODER.upper()}")
    log_info(f"   CPU Threads : {HW_SETTINGS['cpu_threads']}")
    log_info("-" * 60)


# ==============================================================================
# UTILITIES
# ==============================================================================
def get_duration(file_path, stream_type="v"):
    """Get precise duration in seconds."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        f"{stream_type}:0",
        "-show_entries",
        "stream=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        file_path,
    ]
    try:
        out = subprocess.check_output(cmd).decode().strip()
        if out == "N/A" or not out:
            cmd = [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                file_path,
            ]
            out = subprocess.check_output(cmd).decode().strip()
        return float(out)
    except Exception:
        return 0.0


def get_fps(file_path):
    """Detects average frame rate."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=r_frame_rate",
        "-of", "default=noprint_wrappers=1:nokey=1",
        file_path,
    ]
    try:
        out = subprocess.check_output(cmd).decode().strip()
        if "/" in out:
            num, den = map(int, out.split("/"))
            return num / den
        return float(out)
    except Exception:
        return 29.97  # Fallback


def get_start_time(file_path, stream_type="v"):
    """Get stream start_time in seconds."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", f"{stream_type}:0",
        "-show_entries", "stream=start_time",
        "-of", "default=noprint_wrappers=1:nokey=1",
        file_path,
    ]
    try:
        out = subprocess.check_output(cmd).decode().strip()
        if out and out != "N/A":
            return float(out)
        return 0.0
    except Exception:
        return 0.0


def get_vpy_info(vspipe_exe, script_path, venv_root):
    """
    Runs vspipe --info to get frame count and FPS.
    Returns: (frames, fps_float) or (None, None) on error.
    """
    try:
        # Set environment for valid loading
        vspipe_env = os.environ.copy()
        vspipe_env["PYTHONHOME"] = os.path.join(venv_root, "vs")
        vspipe_env["PYTHONPATH"] = os.path.join(venv_root, "Lib", "site-packages")

        cmd = [vspipe_exe, "--info", script_path, "-"]

        # Use a reasonable timeout to avoid hanging on bad scripts
        output = subprocess.check_output(cmd, env=vspipe_env, stderr=subprocess.STDOUT, timeout=30).decode()

        frames = None
        fps = None

        for line in output.splitlines():
            line = line.strip()
            if line.startswith("Frames:"):
                try:
                    frames = int(line.split(":")[1].strip())
                except ValueError:
                    pass
            elif line.startswith("FPS:"):
                # Format: FPS: 30000/1001 (29.970 fps)
                try:
                    parts = line.split(":")[1].split("(")[0].strip()  # Get "30000/1001"
                    if "/" in parts:
                        num, den = map(int, parts.split("/"))
                        fps = num / den
                    else:
                        fps = float(parts)
                except Exception:
                    pass

        return frames, fps

    except subprocess.CalledProcessError as e:
        log_error(f"[VSPIPE ERROR] Info check failed: {e.output.decode()}")
        return None, None
    except Exception as e:
        log_error(f"[VSPIPE ERROR] Info check failed: {e}")
        return None, None

# ==============================================================================
# MAIN PIPELINE
# ==============================================================================


def _get_input_files():
    """Gathers input files from CLI args or interactive prompt."""
    files = []
    video_exts = {".mp4", ".mkv", ".avi", ".mov", ".ts", ".m2ts", ".mpg", ".mpeg"}

    # 1. Drag & Drop (CLI Args)
    if len(sys.argv) > 1:
        log_info(f">> Arguments Detected: {len(sys.argv) - 1} items")
        for arg in sys.argv[1:]:
            path = Path(arg)
            if path.is_file() and path.suffix.lower() in video_exts:
                files.append(path)
            elif path.is_dir():
                log_info(f">> Scanning folder: {path.name}")
                files.extend(
                    [
                        f
                        for f in path.iterdir()
                        if f.is_file() and f.suffix.lower() in video_exts
                    ]
                )

    # 2. Interactive Prompt
    else:
        try:
            print("\n" + "-" * 60)
            print(" [HOW TO USE]")
            print(" 1. Drag and Drop a video file (or folder) onto this window.")
            print(" 2. Or paste the file path below.")
            print("-" * 60 + "\n")

            user_input = input(">> Please Drag & Drop a video file here and press Enter: ").strip()

            # Log the manual input for debugging context
            log_debug(f"User Input: {user_input}")

            # Clean quotes
            if user_input.startswith('"') and user_input.endswith('"'):
                user_input = user_input[1:-1]
            elif user_input.startswith("'") and user_input.endswith("'"):
                user_input = user_input[1:-1]

            if user_input:
                path = Path(user_input)
            else:
                # DEFAULT: Default to 'input' folder if it exists
                path = Path("input")
                if path.exists() and path.is_dir():
                    log_info(">> No input detected. Defaulting to 'input' folder.")
                else:
                    return []  # Exit if no input and no default folder

            if path.is_file() and path.suffix.lower() in video_exts:
                if "_deinterlaced" not in path.name and "_intermediate" not in path.name:
                    files.append(path)
            elif path.is_dir():
                log_info(f">> Scanning folder: {path.name}")
                files.extend(
                    [
                        f
                        for f in path.iterdir()
                        if f.is_file()
                        and f.suffix.lower() in video_exts
                        and "_deinterlaced" not in f.name
                        and "_intermediate" not in f.name
                    ]
                )
        except (EOFError, KeyboardInterrupt):
            pass

    return files


def process_video(input_path):
    """Runs the pipeline for a single video file."""
    # Determine Output Path (Same folder as input)
    out_ext = ".mov" if ENCODER == "prores" else ".mkv"
    output_path = input_path.parent / (input_path.stem + "_deinterlaced" + out_ext)

    # [ROBUSTNESS] RESUME LOGIC (Final Output)
    if output_path.exists() and output_path.stat().st_size > 1024:
        log_info(f"\n[SKIP] {output_path.name} already exists.")
        return

    log_info(f"\n[Processing] {input_path.name}")
    log_info(f"   -> Output: {output_path.name}")

    work_dir = input_path.parent
    # [ROBUSTNESS] UNIQUE TEMP NAMES
    temp_vpy = work_dir / f"{input_path.stem}_temp_script.vpy"
    temp_video = work_dir / f"{input_path.stem}_intermediate.mov"

    try:
        # [ROBUSTNESS] RESUME LOGIC (Intermediate)
        intermediate_exists = temp_video.exists() and temp_video.stat().st_size > 1024

        if intermediate_exists:
            log_info(
                "   -> Found existing intermediate master. Skipping Deinterlace step."
            )
        else:
            # 1. Generate Script
            log_info("   [1/4] Generating processing script...")
            create_vpy_script(
                str(input_path),
                str(temp_vpy),
                DEINTERLACE_MODE,
                override_settings=None,
            )

            # 2. Single-Pass Encoding & Muxing (Optimized)
            log_info("   [2/3] Single-Pass Processing (Deinterlace -> Encode + Sync -> Mux)...")

            # [PERFORMANCE] Use compiled vspipe.exe for C++ speed (approx 4x faster)
            venv_root = os.path.dirname(os.path.dirname(sys.executable))
            vspipe_exe = os.path.join(venv_root, "vs", "vspipe.exe")

            if not os.path.exists(vspipe_exe):
                vspipe_exe = shutil.which("vspipe")

            if not vspipe_exe or not os.path.exists(vspipe_exe):
                log_error("   [ERROR] vspipe.exe not found. Please run install.ps1.")
                return

            log_debug(f"[DEBUG] Using VSPipe: {vspipe_exe}")

            # 2a. Pre-Flight Check: Get Duration & Calculate Sync Drift
            # We must know the video duration *before* we start encoding to build the filter chain.
            v_frames, v_fps = get_vpy_info(vspipe_exe, str(temp_vpy), venv_root)

            dur_audio_src = get_duration(str(input_path), "a")
            dur_video_new = 0.0

            if v_frames and v_fps and v_fps > 0:
                dur_video_new = v_frames / v_fps
                log_info(f"   [SYNC CHECK] Video: {dur_video_new:.4f}s ({v_frames} frames @ {v_fps:.3f} fps)")
            else:
                log_info("   [SYNC WARNING] Could not determine video duration from script. Drift correction might be skipped.")

            # Calculate Drift (Logic identical to previous, just moved up)
            speed_factor = 1.0
            use_drift_correction = CONFIG.get("auto_drift_correction", True)

            if use_drift_correction and dur_audio_src > 0 and dur_video_new > 0:
                drift_seconds = abs(dur_audio_src - dur_video_new)
                speed_factor = dur_audio_src / dur_video_new
                speed_change_pct = abs(1.0 - speed_factor) * 100

                drift_cfg = CONFIG.get("drift_guard_thresholds", {})
                MAX_SKEW_PERCENT = float(drift_cfg.get("max_drift_percent", 1.5))
                MIN_CORRECTION_SEC = float(drift_cfg.get("min_drift_seconds", 0.010))
                should_correct = True
                reason = ""

                if speed_change_pct > MAX_SKEW_PERCENT:
                    should_correct = False
                    reason = f"EXCESSIVE DRIFT (> {MAX_SKEW_PERCENT}%). Likely content mismatch/padding"
                    log_error(f"   [SYNC WARNING] Audio differs by {speed_change_pct:.4f}% ({drift_seconds:.2f}s). This is too large for clock drift.")
                    log_error("   [SYNC WARNING] Assuming extra silence/padding. Disabling Stretch to preserve audio quality.")
                elif drift_seconds < MIN_CORRECTION_SEC:
                    should_correct = False
                    reason = f"negligible drift ({drift_seconds:.3f}s < 10ms)"
                elif speed_factor < 1.0:
                    # [SYNC FIX] Negative Drift (Audio < Video).
                    # This usually means the audio recording stopped early (truncation) or video has tail padding.
                    # Stretching this (slowing it down) causes "slow motion" audio and desync.
                    should_correct = False
                    reason = "Negative Drift (Audio < Video). Assuming truncation/padding. Skipping Stretch."

                if not should_correct:
                    log_info(f"   [SYNC] Skipping correction: {reason}.")
                    speed_factor = 1.0
                else:
                    try:
                        log_info(f"   [SYNC] Applying correction: {speed_change_pct:.5f}% speed change (Factor: {speed_factor:.8f})")
                    except ValueError:
                        log_info(f"   [SYNC] Applying correction: Factor: {speed_factor}")
            else:
                log_info("   [SYNC] Auto Drift Correction DISABLED (or invalid durations). Using raw speed 1.0.")

            # 2b. Build Output Command (Single Pass)
            # [SYNC FIX] Compensate for lost start_time offset and QTGMC delay
            src_video_start = get_start_time(str(input_path), "v")
            src_audio_start = get_start_time(str(input_path), "a")
            start_time_offset = src_video_start - src_audio_start

            # QTGMC's temporal analysis introduces a small video processing delay (~1 frame)
            QTGMC_DELAY = 0.040  # 40ms = 1 frame @ 25fps (PAL)

            total_offset = AUDIO_OFFSET + start_time_offset + QTGMC_DELAY
            log_info(f"   Offsets: StartTime={start_time_offset:+.3f}s | QTGMC={QTGMC_DELAY:+.3f}s | Total Audio Delay={total_offset:+.3f}s")

            # Construct Audio Filter Chain
            has_drift = abs(speed_factor - 1.0) > 1e-9
            has_offset = abs(total_offset) > 0.001

            filter_chain = ""
            if has_drift or has_offset:
                filter_chain = f"[1:a]atempo={speed_factor:.15f}[drifted];"

                if total_offset > 0.001:  # Audio needs to be delayed
                    delay_ms = int(total_offset * 1000)
                    filter_chain += f"[drifted]adelay={delay_ms}|{delay_ms}[aout]"
                elif total_offset < -0.001:  # Audio needs to be trimmed
                    trim_start = abs(total_offset)
                    filter_chain += f"[drifted]atrim=start={trim_start},asetpts=PTS-STARTPTS[aout]"
                else:
                    filter_chain += "[drifted]anull[aout]"
            else:
                filter_chain = "[1:a]anull[aout]"

            # Video Encoding Args
            final_video_args = []
            if ENCODER == "prores":
                final_video_args = [
                    "-c:v", "prores_ks",
                    "-profile:v", "3",
                    "-vendor", "apl0",
                    "-pix_fmt", "yuv422p10le",
                ]
            elif ENCODER == "av1":
                if HW_SETTINGS["use_gpu_opencl"]:
                    # [GPU] NVENC AV1
                    final_video_args = [
                        "-c:v", "av1_nvenc",
                        "-preset", "p7",
                        "-cq", "18",
                        "-pix_fmt", "yuv420p10le",
                    ]
                else:
                    # [CPU] SVT-AV1
                    final_video_args = [
                        "-c:v", "libsvtav1",
                        "-preset", "4",
                        "-crf", "16",
                        "-pix_fmt", "yuv420p10le",
                        "-threads", str(HW_SETTINGS["cpu_threads"]),
                    ]

            # [AUDIO SELECTION]
            effective_audio_codec = AUDIO_CODEC
            if ENCODER == "prores" and AUDIO_CODEC == "aac":
                effective_audio_codec = "pcm_s16le"
                log_info("   [AUDIO] ProRes detected with default AAC. Upgrading to lossless PCM for archival.")

            audio_args = ["-c:a", effective_audio_codec]
            if effective_audio_codec in ["aac", "libmp3lame", "ac3"]:
                audio_args.extend(["-b:a", AUDIO_BITRATE])
            # 2c. Execute Single Pass
            # Pipe: VSPipe -> FFmpeg (Input 0)
            # File: Input File -> FFmpeg (Input 1 - Audio)

            vspipe_args = [vspipe_exe, str(temp_vpy), "-", "-c", "y4m", "-p"]

            ffmpeg_exe = shutil.which("ffmpeg")
            if not ffmpeg_exe:
                log_error("   [ERROR] ffmpeg not found in PATH.")
                return

            final_cmd = (
                [
                    ffmpeg_exe,
                    "-y",
                    "-hide_banner",
                    "-loglevel", "info",
                    "-threads", str(HW_SETTINGS["cpu_threads"]),
                    "-i", "pipe:",         # Input 0: Video Pipe
                    "-i", str(input_path),  # Input 1: Original Audio source
                    "-filter_complex", filter_chain,
                    "-map", "0:v",
                    "-map", "[aout]",
                ]
                + final_video_args
                + audio_args
                + [str(output_path)]
            )

            # Set PYTHONHOME and PYTHONPATH for vspipe.exe embedded Python
            vspipe_env = os.environ.copy()
            vspipe_env["PYTHONHOME"] = os.path.join(venv_root, "vs")
            vspipe_env["PYTHONPATH"] = os.path.join(venv_root, "Lib", "site-packages")

            log_debug(f"[DEBUG] VSPipe command: {' '.join(vspipe_args)}")
            log_debug(f"[DEBUG] FFmpeg Single-Pass command: {' '.join(final_cmd)}")

            # Increase buffer size for pipe
            PIPE_BUF = 10 * 1024 * 1024

            p1 = subprocess.Popen(vspipe_args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=vspipe_env, bufsize=PIPE_BUF)
            ACTIVE_PROCS.append(p1)

            t_log = threading.Thread(target=log_vspipe_output, args=(p1.stderr,))
            # Capture vspipe stderr for logging
            t_log.daemon = True
            t_log.start()

            p2 = subprocess.Popen(final_cmd, stdin=p1.stdout, stderr=subprocess.PIPE, universal_newlines=True, bufsize=PIPE_BUF)
            ACTIVE_PROCS.append(p2)
            p1.stdout.close()

            # Monitor Progress
            if v_frames and v_frames > 0:
                total_duration = dur_video_new
            else:
                total_duration = get_duration(str(input_path))  # Fallback

            if total_duration == 0:
                total_duration = 1

            proc_start_time = time.time()

            while True:
                line = p2.stderr.readline()
                if not line and p2.poll() is not None:
                    break

                if line:
                    line = line.strip()
                    # log_debug(f"[FFmpeg] {line}")

                    seconds, time_str, speed_str = parse_ffmpeg_time(line)
                    if seconds:
                        percent = (seconds / total_duration) * 100
                        percent = min(max(percent, 0), 100)

                        # ETA Calculation
                        eta_str = ""
                        try:
                            if percent > 0:
                                elapsed = time.time() - (proc_start_time or time.time())
                                if not proc_start_time:
                                    proc_start_time = time.time() - 0.1  # Init

                                total_estimated = elapsed / (percent / 100)
                                remaining = total_estimated - elapsed
                                eta_str = time.strftime('%H:%M:%S', time.gmtime(remaining))
                        except Exception:
                            pass

                        update_progress(percent, "Processing Single-Pass...", time_str, speed_str, eta_str)

            sys.stderr.write("\n")

            p2.wait()
            
            # [CRITICAL] Terminate vspipe to release file locks (ffindex, source file)
            try:
                p1.terminate()
                p1.wait(timeout=2.0)
            except Exception:
                p1.kill()

            if p1 in ACTIVE_PROCS:
                ACTIVE_PROCS.remove(p1)
            if p2 in ACTIVE_PROCS:
                ACTIVE_PROCS.remove(p2)

            # Join logging thread to ensure it finishes before we continue
            try:
                t_log.join(timeout=2.0)
            except Exception:
                pass

            if p2.returncode != 0:
                log_error(f"   [ERROR] Single-Pass encoding failed (Code: {p2.returncode}).")
                return

            # [REPORT]
            drift_pct = (speed_factor - 1.0) * 100
            log_info("\n   [SYNC REPORT]")
            log_info(f"     > Drift Correction : {drift_pct:+.4f}% speed change (Factor: {speed_factor:.8f})")
            if abs(AUDIO_OFFSET) > 0.0001:
                log_info(f"     > Manual Offset    : {AUDIO_OFFSET:+.3f}s")
            else:
                log_info("     > Manual Offset    : None")

        # [ROBUSTNESS] AUTO-CLEANUP
        log_info("   -> Cleanup...")
        cleanup_temp_files(work_dir, input_path.stem)
        log_info("   -> DONE.")

    except Exception as e:
        log_error(f"   [CRITICAL ERROR]: {e}")
        # Don't delete intermediate on error to allow resume
        if temp_vpy.exists():
            temp_vpy.unlink()
    finally:
        # Final safety cleanup for process tracking
        if 'p1' in locals() and p1 in ACTIVE_PROCS:
            ACTIVE_PROCS.remove(p1)
        if 'p2' in locals() and p2 in ACTIVE_PROCS:
            ACTIVE_PROCS.remove(p2)
        if 't_log' in locals() and t_log.is_alive():
            try:
                t_log.join(timeout=0.1)
            except Exception:
                pass


def main():
    log_info("\n[SYSTEM INITIALIZATION]")
    update_progress(10, "Initializing Core Systems...")
    time.sleep(0.2)
    # ... (Rest of main remains mostly same, just replace prints)

    time.sleep(0.2)

    update_progress(40, "Scanning Hardware...")
    cpu_name = get_cpu_name()
    gpu_name = get_gpu_name()
    time.sleep(0.2)

    update_progress(80, f"Optimizing for: {gpu_name}")
    check_requirements()

    update_progress(100, "Initialization Complete.")
    time.sleep(0.3)

    _show_banner(cpu_name, gpu_name)

    files = _get_input_files()

    if not files:
        log_info(">> No valid files selected.")
        input("Press Enter to exit...")
        return

    log_info(f"\n[System] Found {len(files)} files in queue.")
    log_info("[System] Starting Batch Processing...")

    for f in files:
        process_video(f)

    log_info("\n" + "=" * 60)
    log_info("   BATCH PROCESSING COMPLETE")
    log_info("=" * 60)
    input("Press Enter to exit...")


if __name__ == "__main__":
    main()
