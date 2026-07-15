"""Logging, system checks, and shared utility helpers for the pipeline."""

import atexit
import contextlib
import logging
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime
from typing import List

# ==============================================================================
#  LOGGING & PROCESS MANAGEMENT
# ==============================================================================

# Configure Logging - always write to project root


def get_project_root():
    """Return the project root path for both source and frozen execution modes."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


SCRIPT_DIR = get_project_root()
log_file = os.path.join(SCRIPT_DIR, "auto_vhs_debug.txt")
logger = logging.getLogger("AutoVHS")
logger.setLevel(logging.DEBUG)
DLL_DIRECTORY_HANDLES: List[object] = []


def _is_python_launcher_name(base_name: str) -> bool:
    """Return whether a command basename matches a Python launcher."""
    return base_name in {"python", "python.exe", "py", "py.exe"} or base_name.startswith("python")


def _is_vspipe_script_name(base_name: str) -> bool:
    """Return whether a command basename looks like a Python vspipe wrapper."""
    return base_name.startswith("vspipe") and base_name.endswith(".py")


def _is_windows_vspipe_launcher(executable_path: str, base_name: str) -> bool:
    """Return whether a Windows Scripts entry point is launching vspipe."""
    scripts_segment = f"{os.sep}scripts{os.sep}"
    return scripts_segment in executable_path and base_name.startswith("vspipe") and base_name.endswith(".exe")


def is_python_vspipe_launcher(vspipe_exe):
    """Detect whether a vspipe command likely runs through a Python launcher."""
    if not vspipe_exe:
        return False

    exe = os.path.abspath(str(vspipe_exe)).lower()
    base = os.path.basename(exe)
    if _is_python_launcher_name(base):
        return True
    if _is_windows_vspipe_launcher(exe, base):
        return True
    return _is_vspipe_script_name(base)


def _resolve_venv_root(base_dir: str) -> str:
    """Return the preferred local venv root, falling back to the current interpreter."""
    venv_root = os.path.join(base_dir, ".venv")
    if os.path.exists(venv_root):
        return venv_root
    return os.path.dirname(os.path.dirname(sys.executable))


def _get_vapoursynth_plugin_dir(vs_root: str) -> str:
    """Return the first existing VapourSynth plugin directory."""
    for folder_name in ("plugins", "vs-plugins"):
        candidate = os.path.join(vs_root, folder_name)
        if os.path.exists(candidate):
            return candidate
    return os.path.join(vs_root, "plugins")


def _build_vspipe_path_entries(vs_root: str) -> list[str]:
    """Return PATH entries that should be added for VapourSynth execution."""
    paths_to_add = [vs_root]
    plugin_dir = _get_vapoursynth_plugin_dir(vs_root)
    if os.path.exists(plugin_dir):
        paths_to_add.append(plugin_dir)
    return paths_to_add


def _set_vspipe_environment(env: dict[str, str], venv_root: str):
    """Populate a process environment with portable VapourSynth paths."""
    vs_root = os.path.join(venv_root, "vs")
    if not os.path.exists(vs_root):
        return

    env["PYTHONHOME"] = vs_root
    env["PYTHONPATH"] = os.path.join(venv_root, "Lib", "site-packages")
    existing_path = env.get("PATH", "")
    extra_path = os.pathsep.join(_build_vspipe_path_entries(vs_root))
    env["PATH"] = (existing_path + os.pathsep + extra_path) if existing_path else extra_path


def get_vspipe_env():
    """Derived environment variables for VSPipe (Portable)."""
    env = os.environ.copy()
    try:
        env.pop("PYTHONHOME", None)
        env.pop("PYTHONPATH", None)
        base_dir = get_project_root()
        _set_vspipe_environment(env, _resolve_venv_root(base_dir))
    except (OSError, ValueError, RuntimeError, KeyError):
        pass
    return env


# File Handler (DEBUG level -> auto_vhs.log in project root)
file_handler = logging.FileHandler(log_file, mode="w", encoding="utf-8")
file_handler.setLevel(logging.DEBUG)


class ISOFormatter(logging.Formatter):
    """Format logger timestamps as ISO 8601 with milliseconds and timezone."""

    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created).astimezone()
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + dt.strftime("%z")


file_formatter = ISOFormatter("%(asctime)s [%(levelname)s] %(message)s")
file_handler.setFormatter(file_formatter)

# Console Handler (INFO level -> minimal output)
# We write to stderr to avoid interfering with any potential pipe usage
console_handler = logging.StreamHandler(sys.stderr)
console_handler.setLevel(logging.INFO)
console_formatter = logging.Formatter("%(message)s")  # Clean format for user
console_handler.setFormatter(console_formatter)

# Prevent adding handlers multiple times if module is reloaded
if not logger.handlers:
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)


def log_debug(msg):
    """Log a debug message and flush handlers if available."""
    _log_with_flush(logger.debug, msg)


def log_info(msg):
    """Log an info message and flush handlers if available."""
    _log_with_flush(logger.info, msg)


def log_error(msg):
    """Log an error message and flush handlers if available."""
    _log_with_flush(logger.error, msg)


def _log_with_flush(log_method, msg):
    """Call logger method and flush handlers while swallowing logging errors."""
    try:
        log_method(msg)
        for handler in logger.handlers:
            try:
                handler.flush()
            except (ValueError, RuntimeError, AttributeError):
                pass
    except (ValueError, RuntimeError, AttributeError):
        pass


# Process Tracking & Signal Handling
ACTIVE_PROCS: List[subprocess.Popen] = []


def _terminate_active_process(process: subprocess.Popen):
    """Terminate one tracked subprocess, escalating to kill if needed."""
    if process.poll() is not None:
        return
    try:
        log_debug(f"[SYSTEM] Terminating process {process.pid}...")
        process.terminate()
        time.sleep(0.1)
        if process.poll() is None:
            process.kill()
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
        pass


def cleanup_on_exit(signum=None, _frame=None):
    """Terminates all registered subprocesses and exits."""
    if signum:
        sig_name = signal.Signals(signum).name
        log_debug(f"[SYSTEM] Received signal {sig_name}. Shutting down...")

    for process in ACTIVE_PROCS:
        _terminate_active_process(process)

    if signum:
        sys.exit(1)


# Register cleanup for normal exits and various signals
atexit.register(cleanup_on_exit)
signal.signal(signal.SIGINT, cleanup_on_exit)
signal.signal(signal.SIGTERM, cleanup_on_exit)
if platform.system() == "Windows":
    # SIGBREAK is sent when the console window is closed on Windows
    SIGBREAK_SIGNAL = getattr(signal, "SIGBREAK", None)
    if SIGBREAK_SIGNAL is not None:
        signal.signal(SIGBREAK_SIGNAL, cleanup_on_exit)


def run_command(args, **kwargs):
    """Executes a command and tracks it for cleanup.

    Callers that pass stdout=subprocess.PIPE or stderr=subprocess.PIPE must
    drain those streams themselves, and wait for process completion.
    """
    ACTIVE_PROCS[:] = [proc for proc in ACTIVE_PROCS if proc.poll() is None]
    process_stack = contextlib.ExitStack()
    process = process_stack.enter_context(subprocess.Popen(args, **kwargs))
    process_stack.pop_all()
    ACTIVE_PROCS.append(process)
    return process


def _add_venv_to_path(venv_root):
    """Adds venv Scripts or bin folder to PATH."""
    venv_scripts = os.path.join(venv_root, "Scripts")
    if not os.path.exists(venv_scripts):
        venv_scripts = os.path.join(venv_root, "bin")

    if os.path.exists(venv_scripts):
        os.environ["PATH"] = venv_scripts + os.pathsep + os.environ["PATH"]


def _add_windows_dll_directory(path_value: str):
    """Best-effort add a DLL search path on Windows."""
    if platform.system() != "Windows" or not hasattr(os, "add_dll_directory"):
        return
    try:
        handle = os.add_dll_directory(path_value)
        DLL_DIRECTORY_HANDLES.append(handle)
    except (OSError, ValueError):
        pass


def _setup_vapoursynth_portable(venv_root):
    """Configures environment for portable VapourSynth."""
    venv_vs = os.path.join(venv_root, "vs")
    if not os.path.exists(venv_vs):
        return

    os.environ["PATH"] = os.environ["PATH"] + os.pathsep + venv_vs
    _add_windows_dll_directory(venv_vs)

    vs_plugins = _get_vapoursynth_plugin_dir(venv_vs)
    if os.path.exists(vs_plugins):
        os.environ["VAPOURSYNTH_PLUGIN_PATH"] = vs_plugins


def setup_environment():
    """Setup FFmpeg and VapourSynth paths from local venv."""
    try:
        base_dir = get_project_root()
        venv_root = os.path.join(base_dir, ".venv")

        _add_venv_to_path(venv_root)
        _setup_vapoursynth_portable(venv_root)
    except (OSError, ValueError):
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
        log_error(f"CRITICAL ERROR: The following tools are not in your SYSTEM PATH: {', '.join(missing)}")
        log_error("Please install VapourSynth and FFmpeg and add them to your PATH.")
        sys.exit(1)


def parse_ffmpeg_time(line_str):
    """
    Extracts time in seconds, timestamp string, and speed from FFmpeg output.
    Returns: (seconds_float, time_str, speed_str)
    """
    if not line_str:
        return None, None, None

    time_match = re.search(r"time=(\d{2}:\d{2}:\d{2}(?:\.\d+)?)", line_str)
    speed_match = re.search(r"speed=\s*(\d+\.?\d*x)", line_str)

    seconds, time_s = _parse_ffmpeg_timestamp_match(time_match)
    speed_s = _format_ffmpeg_speed_match(speed_match)
    return seconds, time_s, speed_s


def _normalize_ffmpeg_timestamp_parts(hours, minutes, seconds):
    """Normalize parsed FFmpeg time parts into HH:MM:SS,mmm components."""
    h_int = int(hours)
    m_int = int(minutes)
    s_int = int(seconds)
    ms_int = int(round((seconds - s_int) * 1000))

    if ms_int >= 1000:
        ms_int -= 1000
        s_int += 1
    if s_int >= 60:
        s_int -= 60
        m_int += 1
    if m_int >= 60:
        m_int -= 60
        h_int += 1
    return h_int, m_int, s_int, ms_int


def _parse_ffmpeg_timestamp_match(time_match):
    """Parse the regex match for FFmpeg time output."""
    if not time_match:
        return None, None

    original_ts = time_match.group(1)
    try:
        hours, minutes, seconds = (float(part) for part in original_ts.split(":"))
        total_seconds = hours * 3600 + minutes * 60 + seconds
        h_int, m_int, s_int, ms_int = _normalize_ffmpeg_timestamp_parts(hours, minutes, seconds)
        return total_seconds, f"{h_int:02d}:{m_int:02d}:{s_int:02d},{ms_int:03d}"
    except (ValueError, IndexError):
        return None, original_ts


def _format_ffmpeg_speed_match(speed_match):
    """Parse and normalize the FFmpeg speed token."""
    if not speed_match:
        return None
    speed_s = speed_match.group(1)
    try:
        return f"{float(speed_s.replace('x', '')):.2f}x"
    except ValueError:
        return speed_s


def _should_delete_temp_file(file_path) -> bool:
    """Return whether a matched file looks like a generated temp artifact."""
    if not file_path.is_file():
        return False
    temp_markers = ("temp", "intermediate", "ffindex", "lwi")
    return any(marker in file_path.name for marker in temp_markers)


def cleanup_temp_files(work_dir, stem):
    """Robust cleanup of all temporary files."""
    patterns = [
        f"{stem}_temp_script.vpy",
        f"{stem}_intermediate.mov",
        f"{stem}_intermediate.mkv",
        f"{stem}.*ffindex",  # Clean FFMS2 index files
        f"{stem}.*lwi",  # Clean LSMASH index files
        "*.vpy",  # Safety: Clean stray VPYs
    ]

    for p_str in patterns:
        for file_path in work_dir.glob(p_str):
            if not _should_delete_temp_file(file_path):
                continue
            try:
                file_path.unlink()
            except OSError:
                pass


def update_progress(percent, message, time_str=None, speed_str=None, eta_str=None, process_name="FFmpeg"):
    """Draws a unified progress bar matching the style: [Process] Status[Bar]  % | Time | ETA | Speed"""
    bar_length = 20

    # Ensure percent is 0-100
    percent = max(0.0, min(100.0, percent))

    filled_length = int(bar_length * percent // 100)
    progress_bar = "█" * filled_length + "░" * (bar_length - filled_length)

    # Format: [Whisper] Transcribing[████░░░░]  74.3% | 00:01:23,000 / 00:05:00,000 | ETA 00:03:45 | 1.50x
    # User example showed TWO spaces before percentage after the bar.
    # Note: {percent:5.1f}% adds one space padding for numbers < 100.
    output = f"\r\033[K[{process_name}] {message}[{progress_bar}] {percent:5.1f}%"

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
    winreg = None


def get_cpu_name():
    """Return a friendly CPU model name when available."""
    try:
        if winreg:
            key_path = r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path)
            processor_name = winreg.QueryValueEx(key, "ProcessorNameString")[0]
            return processor_name.strip()
    except OSError:
        pass
    return platform.processor()


def get_nvidia_gpu_info():
    """Return the first detected NVIDIA GPU index and name, if available."""
    try:
        # Use a direct command (no shell) and keep a hard timeout to avoid hangs.
        output = subprocess.check_output(["nvidia-smi", "-L"], timeout=10).decode().strip()
        if not output:
            return None, None
        for gpu_index, line in enumerate(output.splitlines()):
            if "NVIDIA" in line:
                gpu_name = line.split(":", maxsplit=1)[1].split("(")[0].strip()
                return gpu_index, gpu_name
    except (subprocess.SubprocessError, OSError, ValueError, IndexError):
        pass
    return None, None


def get_gpu_name():
    """Return detected NVIDIA GPU name, or a generic fallback string."""
    _, gpu_name = get_nvidia_gpu_info()
    if gpu_name:
        return gpu_name
    return "Generic / Not Detected"


def _show_banner(cpu, gpu, perf_profile, mode, encoder, config_settings):
    os_info = f"{platform.system()} {platform.release()}"
    banner = [
        " __     ___   _ ____    ____  _____ ___ _   _ _____ _____ ____  _        _    _   _  ____ _____ ____  ",
        " \\ \\   / / | | / ___|  |  _ \\| ____|_ _| \\ | |_   _| ____|  _ \\| |      / \\  | \\ | |/ ___| ____|  _ \\ ",
        "  \\ \\ / /| |_| \\___ \\  | | | |  _|  | ||  \\| | | | |  _| | |_) | |     / _ \\ |  \\| | |   |  _| | |_) |",
        "   \\ V / |  _  |___) | | |_| | |___ | || |\\  | | | | |___|  _ <| |___ / ___ \\| |\\  | |___| |___|  _ < ",
        "    \\_/  |_| |_|____/  |____/|_____|___|_| \\_| |_| |_____|_| \\_\\_____/_/   \\_\\_| \\_|\\____|_____|_| \\_\\",
    ]

    log_info("\n" + "=" * 72)
    log_info("   Auto VHS Deinterlancer - v1.0.2")
    log_info(f"   Running on: {os_info}")
    log_info("=" * 72)
    log_info("")
    for line in banner:
        log_info(line)

    log_info("\n[HARDWARE DETECTED]")
    log_info(f"   CPU : {config_settings['cpu_threads']} Logical Cores ({cpu})")
    log_info(f"   GPU : {gpu}")

    log_info(f"\n[AUTO-TUNED SETTINGS -> Profile: {perf_profile.upper()}]")
    log_info(f"   Mode        : {mode}")
    log_info(f"   Encoder     : {encoder.upper()}")
    log_info(f"   CPU Threads : {config_settings['cpu_threads']}")
    log_info("-" * 72)


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
        out = subprocess.check_output(cmd, timeout=10).decode().strip()
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
            out = subprocess.check_output(cmd, timeout=10).decode().strip()
        return float(out)
    except (subprocess.SubprocessError, OSError, ValueError):
        return 0.0


def get_fps(file_path):
    """Detects average frame rate."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=r_frame_rate",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(file_path),
    ]
    try:
        out = subprocess.check_output(cmd, timeout=10).decode().strip()
        if "/" in out:
            num, den = map(int, out.split("/"))
            return num / den
        return float(out)
    except (subprocess.SubprocessError, OSError, ValueError, ZeroDivisionError):
        return 29.97  # Fallback


def get_start_time(file_path, stream_type="v"):
    """Get stream start_time in seconds."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        f"{stream_type}:0",
        "-show_entries",
        "stream=start_time",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(file_path),
    ]
    try:
        out = subprocess.check_output(cmd, timeout=10).decode().strip()
        if out and out != "N/A":
            return float(out)
        return 0.0
    except (subprocess.SubprocessError, OSError, ValueError):
        return 0.0


__all__ = [
    "get_project_root",
    "is_python_vspipe_launcher",
    "_get_vapoursynth_plugin_dir",
    "get_vspipe_env",
    "log_debug",
    "log_info",
    "log_error",
    "cleanup_on_exit",
    "run_command",
    "setup_environment",
    "check_requirements",
    "parse_ffmpeg_time",
    "cleanup_temp_files",
    "update_progress",
    "get_cpu_name",
    "get_nvidia_gpu_info",
    "get_gpu_name",
    "get_duration",
    "get_fps",
    "get_start_time",
    "logger",
    "subprocess",
    "shutil",
    "signal",
    "platform",
    "time",
    "winreg",
]
