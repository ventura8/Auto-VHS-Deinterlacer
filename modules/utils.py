import os
import sys
import shutil
import signal
import atexit
import time
import platform
import logging
import re
import subprocess
from typing import List

# ==============================================================================
#  LOGGING & PROCESS MANAGEMENT
# ==============================================================================

# Configure Logging - always write to project root


def get_project_root():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


SCRIPT_DIR = get_project_root()
log_file = os.path.join(SCRIPT_DIR, "auto_vhs_debug.txt")
logger = logging.getLogger("AutoVHS")
logger.setLevel(logging.INFO)


def get_vspipe_env():
    """Derived environment variables for VSPipe (Portable)."""
    env = os.environ.copy()
    try:
        base_dir = get_project_root()
        venv_root = os.path.join(base_dir, ".venv")
        if not os.path.exists(venv_root):
            # Fallback
            venv_root = os.path.dirname(os.path.dirname(sys.executable))

        # Portable VS structure
        vs_root = os.path.join(venv_root, "vs")
        if os.path.exists(vs_root):
            env["PYTHONHOME"] = vs_root
            # Standard venv site-packages logic
            env["PYTHONPATH"] = os.path.join(venv_root, "Lib", "site-packages")

            # CRITICAL: Add VS and Plugins to PATH so dependencies are found
            # This fixes ffms2.dll failing to load if it needs adjacent DLLs
            paths_to_add = [vs_root]

            plugin_dir = os.path.join(vs_root, "plugins")
            if not os.path.exists(plugin_dir):
                plugin_dir = os.path.join(vs_root, "vs-plugins")
            if os.path.exists(plugin_dir):
                paths_to_add.append(plugin_dir)

            # Prepend to PATH
            env["PATH"] = os.pathsep.join(paths_to_add) + os.pathsep + env.get("PATH", "")

    except Exception:
        pass
    return env


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

# Prevent adding handlers multiple times if module is reloaded
if not logger.handlers:
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
            try:
                ACTIVE_PROCS.remove(p)
            except ValueError:
                pass


def _add_venv_to_path(venv_root):
    """Adds venv Scripts or bin folder to PATH."""
    venv_scripts = os.path.join(venv_root, "Scripts")
    if not os.path.exists(venv_scripts):
        venv_scripts = os.path.join(venv_root, "bin")

    if os.path.exists(venv_scripts):
        os.environ["PATH"] = venv_scripts + os.pathsep + os.environ["PATH"]


def _setup_vapoursynth_portable(venv_root):
    """Configures environment for portable VapourSynth."""
    venv_vs = os.path.join(venv_root, "vs")
    if not os.path.exists(venv_vs):
        return

    # Add VS to PATH so vspipe can load its DLLs
    os.environ["PATH"] = venv_vs + os.pathsep + os.environ["PATH"]

    # Windows: Ensure DLLs are findable by Python 3.8+
    if platform.system() == "Windows" and hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(venv_vs)
        except Exception:
            pass

    # Set plugin path for VapourSynth plugin autoloading
    vs_plugins = os.path.join(venv_vs, "plugins")
    if not os.path.exists(vs_plugins):
        vs_plugins = os.path.join(venv_vs, "vs-plugins")

    if os.path.exists(vs_plugins):
        os.environ["VAPOURSYNTH_PLUGIN_PATH"] = vs_plugins


def setup_environment():
    """Setup FFmpeg and VapourSynth paths from local venv."""
    try:
        base_dir = get_project_root()
        venv_root = os.path.join(base_dir, ".venv")

        _add_venv_to_path(venv_root)
        _setup_vapoursynth_portable(venv_root)
    except Exception:
        pass


# ==============================================================================
# SYSTEM CHECKS & UTILS
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


def parse_ffmpeg_time(line_str):
    """
    Extracts time in seconds, timestamp string, and speed from FFmpeg output.
    Returns: (seconds_float, time_str, speed_str)
    """
    if not line_str:
        return None, None, None

    # Match time=HH:MM:SS.ms (optional milliseconds)
    time_match = re.search(r"time=(\d{2}:\d{2}:\d{2}(?:\.\d+)?)", line_str)
    # Match speed=...x (e.g. speed=0.98x or speed= 1.2x)
    speed_match = re.search(r"speed=\s*(\d+\.?\d*x)", line_str)

    seconds = None
    time_s = None
    speed_s = None

    if time_match:
        original_ts = time_match.group(1)
        try:
            parts = original_ts.split(":")
            h = float(parts[0])
            m = float(parts[1])
            s = float(parts[2])
            seconds = h * 3600 + m * 60 + s
            
            # Format to HH:MM:SS,mmm (match user requirement)
            h_int = int(h)
            m_int = int(m)
            s_int = int(s)
            ms_int = int(round((s - s_int) * 1000))
            time_s = f"{h_int:02d}:{m_int:02d}:{s_int:02d},{ms_int:03d}"
        except Exception:
            time_s = original_ts
            seconds = None

    if speed_match:
        speed_s = speed_match.group(1)
        # Ensure 2 decimal places if possible (user example showed 10.76x)
        try:
            s_val = float(speed_s.replace("x", ""))
            speed_s = f"{s_val:.2f}x"
        except ValueError:
            pass

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


def update_progress(percent, message, time_str=None, speed_str=None, eta_str=None, process_name="FFmpeg"):
    """Draws a unified progress bar matching the style: [Process] Status[Bar]  % | Time | ETA | Speed"""
    bar_length = 20
    
    # Ensure percent is 0-100
    percent = max(0.0, min(100.0, percent))

    filled_length = int(bar_length * percent // 100)
    bar = "█" * filled_length + "░" * (bar_length - filled_length)

    # Format: [Whisper] Transcribing[████░░░░]  74.3% | 00:01:23,000 / 00:05:00,000 | ETA 00:03:45 | 1.50x
    # User example showed TWO spaces before percentage after the bar.
    # Note: {percent:5.1f}% adds one space padding for numbers < 100.
    output = f"\r\033[K[{process_name}] {message}[{bar}] {percent:5.1f}%"
    
    if time_str:
        output += f" | {time_str}"
    if eta_str:
        output += f" | ETA {eta_str}"
    if speed_str:
        output += f" | {speed_str}"
        
    sys.stderr.write(output)
    sys.stderr.flush()


try:
    import winreg
except ImportError:
    winreg = None  # type: ignore


def get_cpu_name():
    try:
        if winreg:
            key_path = r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path)
            processor_name = winreg.QueryValueEx(key, "ProcessorNameString")[0]
            return processor_name.strip()
    except Exception:
        pass
    return platform.processor()


def get_gpu_name():
    try:
        output = subprocess.check_output("nvidia-smi -L", shell=True).decode().strip()
        if "NVIDIA" in output:
            first_gpu = output.split('\n')[0]
            return first_gpu.split(":")[1].split("(")[0].strip()
    except Exception:
        pass
    return "Generic / Not Detected"


def _show_banner(cpu, gpu, perf_profile, mode, encoder, config_settings):
    log_info("\n" + "=" * 60)
    log_info("   AUTO-VHS-DEINTERLACER - v1.0.0")
    log_info(f"   Running on: {platform.system()} {platform.release()}")
    log_info("=" * 60)

    log_info("\n[HARDWARE DETECTED]")
    log_info(f"   CPU : {cpu}")
    log_info(f"   GPU : {gpu}")

    log_info(f"\n[AUTO-TUNED SETTINGS -> Profile: {perf_profile.upper()}]")
    log_info(f"   Mode        : {mode}")
    log_info(f"   Encoder     : {encoder.upper()}")
    log_info(f"   CPU Threads : {config_settings['cpu_threads']}")
    log_info("-" * 60)


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
        str(file_path),
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
                str(file_path),
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
        str(file_path),
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
        str(file_path),
    ]
    try:
        out = subprocess.check_output(cmd).decode().strip()
        if out and out != "N/A":
            return float(out)
        return 0.0
    except Exception:
        return 0.0
