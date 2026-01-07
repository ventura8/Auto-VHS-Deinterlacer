import os
import sys
import shutil
import threading
import subprocess
import io
from pathlib import Path

from modules.utils import (
    log_info, log_debug, log_error, update_progress, cleanup_temp_files,
    parse_ffmpeg_time, get_duration,
    check_requirements, _show_banner, get_cpu_name, get_gpu_name,
    setup_environment, get_vspipe_env, get_project_root
)

import logging
from modules.config import (
    CONFIG, HW_SETTINGS, PERF_PROFILE, DEINTERLACE_MODE, ENCODER,
    AUDIO_CODEC, AUDIO_BITRATE, AUDIO_OFFSET, DEBUG_MODE
)
from modules.vspipe import create_vpy_script, get_vpy_info, log_vspipe_output


# ==============================================================================
# MAIN PIPELINE
# ==============================================================================


def _scan_directory(path: Path, video_exts: set) -> list:
    """Scans a directory for video files, excluding processed ones."""
    log_info(f">> Scanning folder: {path.name}")
    return [
        f
        for f in path.iterdir()
        if (f.is_file()
            and f.suffix.lower() in video_exts
            and "_deinterlaced" not in f.name
            and "_intermediate" not in f.name)
    ]


def _parse_cli_args(video_exts: set) -> list:
    """Parses command line arguments for input files or folders."""
    files = []
    if len(sys.argv) > 1:
        log_info(f">> Arguments Detected: {len(sys.argv) - 1} items")
        for arg in sys.argv[1:]:
            path = Path(arg)
            if path.is_file() and path.suffix.lower() in video_exts:
                files.append(path)
            elif path.is_dir():
                files.extend(_scan_directory(path, video_exts))
    return files


def _get_interactive_input(video_exts: set) -> list:
    """Gets input files from interactive user prompt."""
    files = []
    try:
        print("\n" + "-" * 60)
        print(" [HOW TO USE]")
        print(" 1. Drag and Drop a video file (or folder) onto this window.")
        print(" 2. Or paste the file path below.")
        print("-" * 60 + "\n")

        user_input = input(">> Please Drag & Drop a video file here and press Enter: ").strip()
        log_debug(f"User Input: {user_input}")

        # Clean quotes
        if user_input.startswith('"') and user_input.endswith('"'):
            user_input = user_input[1:-1]
        elif user_input.startswith("'") and user_input.endswith("'"):
            user_input = user_input[1:-1]

        if user_input:
            path = Path(user_input)
            if path.exists():
                if path.is_file():
                    files.append(path)
                elif path.is_dir():
                    files.extend(_scan_directory(path, video_exts))
        else:
            # Fallback: Check for 'input' folder
            default_input = Path("input")
            if default_input.exists() and default_input.is_dir():
                log_info(">> No input provided. Auto-scanning 'input' folder...")
                files.extend(_scan_directory(default_input, video_exts))
    except KeyboardInterrupt:
        pass
    return files


def get_input_files():
    """Gathers input files from CLI args or interactive prompt."""
    video_exts = {".mp4", ".mkv", ".avi", ".mov", ".ts", ".m2ts", ".mpg", ".mpeg"}

    # 1. Drag & Drop (CLI Args)
    files = _parse_cli_args(video_exts)

    # 2. Interactive Prompt
    if not files:
        files = _get_interactive_input(video_exts)

    return files


def _get_output_path(input_path: Path) -> Path:
    """Constructs the output file path based on config and encoder."""
    stem = input_path.stem
    work_dir = input_path.parent
    suffix_out = CONFIG.get("output_suffix", "_deinterlaced_prores")
    if ENCODER == "av1":
        suffix_out = CONFIG.get("output_suffix_av1", "_deinterlaced_av1")
    output_ext = ".mov" if ENCODER == "prores" else ".mkv"
    return work_dir / f"{stem}{suffix_out}{output_ext}"


def _calculate_audio_sync(input_path: Path, video_duration: float) -> float:
    """Calculates the atempo filter value for audio sync correction."""
    audio_duration = get_duration(str(input_path), "a")

    if not CONFIG.get("auto_drift_correction", True):
        log_info("   [SYNC] Auto-drift correction disabled by config.")
        return 1.0

    diff = audio_duration - video_duration
    abs_diff = abs(diff)

    min_drift = CONFIG.get("audio_drift_min_seconds", 0.05)
    max_drift_pct = CONFIG.get("audio_drift_max_percent", 0.5)
    drift_pct = (abs_diff / video_duration) * 100 if video_duration > 0 else 0

    if abs_diff > min_drift:
        if diff < 0:
            log_info(f"   [SYNC] Audio is shorter than video by {abs_diff:.3f}s. Ignoring.")
        elif drift_pct > max_drift_pct:
            log_info(f"   [SYNC] Drift too large ({drift_pct:.2f}% / {abs_diff:.3f}s). Ignoring safely.")
        else:
            log_info(f"   [SYNC] Correction needed: {abs_diff:.3f}s drift detected.")
            return audio_duration / video_duration
    else:
        log_info(f"   [SYNC] Perfect Sync (Drift: {abs_diff:.3f}s). No correction needed.")
    return 1.0


def _build_ffmpeg_cmd(input_path: Path, output_file: Path, atempo: float, fps: float = 30000 / 1001, width: int = 720, height: int = 576, pixel_format: str = "yuv420p16le") -> list:
    """Builds the FFmpeg command line."""
    ffmpeg_exe = shutil.which("ffmpeg")
    # Raw Video Input Args (Dynamic Pixel Format)
    # -f rawvideo -vcodec rawvideo -pix_fmt {pixel_format} -s WxH -r FPS
    cmd = [
        ffmpeg_exe, "-y",
        "-f", "rawvideo", "-vcodec", "rawvideo",
        "-s", f"{width}x{height}", "-r", str(fps),
        "-pix_fmt", pixel_format,
        "-i", "-",
        "-i", str(input_path), "-map", "0:v:0", "-map", "1:a:0"
    ]

    if ENCODER == "prores":
        cmd.extend([
            "-c:v", "prores_ks", "-profile:v", "3", "-vendor", "apl0",
            "-bits_per_mb", "8000", "-pix_fmt", "yuv422p10le"
        ])
    else:
        cmd.extend([
            "-c:v", "libsvtav1", "-preset", "6", "-crf", "22", "-pix_fmt", "yuv420p10le"
        ])

    audio_filters = []
    if atempo != 1.0:
        audio_filters.append(f"atempo={atempo:.6f}")
    if AUDIO_OFFSET != 0:
        delay_ms = int(AUDIO_OFFSET * 1000)
        audio_filters.append(f"adelay={delay_ms}|{delay_ms}")

    if audio_filters:
        cmd.extend(["-af", ",".join(audio_filters)])

    cmd.extend(["-c:a", AUDIO_CODEC, "-b:a", str(AUDIO_BITRATE), str(output_file)])
    return cmd


def _run_encoding_pipeline(vspipe_cmd, ffmpeg_cmd, temp_script, duration_sec):
    """Executes the VS->FFmpeg pipeline and monitors progress."""
    try:
        vspipe_env = get_vspipe_env()
        # If running vspipe via python script, DO NOT override PYTHONHOME/PYTHONPATH
        # as it will break the current python interpreter's startup (missing encodings)
        if vspipe_cmd[0] == sys.executable:
            vspipe_env.pop("PYTHONHOME", None)
            vspipe_env.pop("PYTHONPATH", None)

        p_vspipe = subprocess.Popen(vspipe_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=vspipe_env)
        p_ffmpeg = subprocess.Popen(ffmpeg_cmd, stdin=p_vspipe.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        if p_vspipe.stdout:
            p_vspipe.stdout.close()

        t_vspipe = threading.Thread(target=log_vspipe_output, args=(p_vspipe.stderr,))
        t_vspipe.daemon = True
        t_vspipe.start()

        if p_ffmpeg.stderr:
            stderr_lines = []
            stderr_reader = io.TextIOWrapper(p_ffmpeg.stderr, encoding="utf-8", errors="replace")
            for line in stderr_reader:
                line_str = line.strip()
                stderr_lines.append(line_str)
                if len(stderr_lines) > 20:
                    stderr_lines.pop(0)

                if "frame=" in line_str:
                    sec, current_ts, speed = parse_ffmpeg_time(line_str)
                    if sec and duration_sec > 0:
                        pct = (sec / duration_sec) * 100

                        # Calculate ETA and Total Duration String (HH:MM:SS,mmm)
                        total_ts = "00:00:00,000"
                        if duration_sec > 0:
                            th, tr = divmod(duration_sec, 3600)
                            tm, ts = divmod(tr, 60)
                            ts_int = int(ts)
                            ms_int = int(round((ts - ts_int) * 1000))
                            total_ts = f"{int(th):02d}:{int(tm):02d}:{ts_int:02d},{ms_int:03d}"

                        eta_str = "--:--:--"
                        if speed:
                            try:
                                speed_val = float(speed.replace("x", ""))
                                if speed_val > 0:
                                    remaining_video_sec = duration_sec - sec
                                    remaining_real_sec = remaining_video_sec / speed_val
                                    m, s = divmod(int(remaining_real_sec), 60)
                                    h, m = divmod(m, 60)
                                    eta_str = f"{h:02d}:{m:02d}:{s:02d}"
                            except ValueError:
                                pass

                        time_display = f"{current_ts} / {total_ts}"
                        update_progress(pct, "Encoding", time_display, speed, eta_str, process_name="FFmpeg")

        p_ffmpeg.wait()
        p_vspipe.wait()

        if p_ffmpeg.returncode == 0:
            log_info("\n\n[SUCCESS] Deinterlacing finished.")
            if temp_script.exists():
                try:
                    os.remove(temp_script)
                except OSError:
                    pass
            return True
        else:
            log_error(f"\n[ERROR] FFmpeg failed with exit code {p_ffmpeg.returncode}")
            log_error(">> Last 20 lines of FFmpeg Error Log:")
            for err_line in stderr_lines:
                log_error(f"   {err_line}")
            return False

    except Exception as e:
        log_error(f"Unexpected error during processing: {e}")
        return False


def process_video(input_path: Path):
    """Refined processing pipeline with restart handling and robust piping."""
    if DEBUG_MODE:
        logging.getLogger("AutoVHS").setLevel(logging.DEBUG)

    if not input_path.exists():
        log_error(f"Input not found: {input_path}")
        return

    log_info(f"\n[JOB START] Processing: {input_path.name}")
    log_info("-" * 40)

    work_dir = input_path.parent
    stem = input_path.stem
    output_file = _get_output_path(input_path)

    temp_script = work_dir / f"{stem}_temp_script.vpy"
    cleanup_temp_files(work_dir, stem)

    # 1. Resume / Integrity Check
    if output_file.exists():
        # Check if previous output is valid (has duration)
        existing_duration = get_duration(str(output_file))
        if existing_duration > 0:
            log_info(f"   [SKIP] Output exists and valid: {output_file.name}")
            cleanup_temp_files(work_dir, stem)
            return
        else:
            log_info(f"   [WARNING] Output exists but seems corrupted (0 duration). Overwriting: {output_file.name}")

    # 2. Atomic Write Setup
    # Use _part.extension instead of .extension.part so FFmpeg detects format automatically
    temp_output = output_file.with_name(f"{output_file.stem}_part{output_file.suffix}")

    log_info(">> Generating VapourSynth Restoration Script...")
    create_vpy_script(str(input_path), str(temp_script), DEINTERLACE_MODE)

    log_info(">> Verifying Script with vspipe...")
    vspipe_exe = shutil.which("vspipe")
    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    venv_root = os.path.join(script_dir, ".venv")
    if not os.path.exists(venv_root):
        venv_root = os.path.dirname(os.path.dirname(sys.executable))

    total_frames, fps, width, height, fmt_name = get_vpy_info(vspipe_exe, str(temp_script), venv_root)
    duration_sec = total_frames / (fps if fps else 29.97) if total_frames else get_duration(str(input_path))

    # Default to invalid/safe if failed
    if not width: width = 720
    if not height: height = 576

    # Map VS format to FFmpeg pix_fmt
    # VS format names: YUV420P8, YUV420P10, YUV420P16, YUV422P10, YUV444P10, etc.
    vs_to_ffmpeg_map = {
        "YUV420P8": "yuv420p",
        "YUV420P10": "yuv420p10le",
        "YUV420P12": "yuv420p12le",
        "YUV420P14": "yuv420p14le",
        "YUV420P16": "yuv420p16le",
        "YUV422P8": "yuv422p",
        "YUV422P10": "yuv422p10le",
        "YUV422P16": "yuv422p16le",
        "YUV444P8": "yuv444p",
        "YUV444P10": "yuv444p10le",
        "YUV444P16": "yuv444p16le"
    }

    # If info failed, use defaults (unsafe, but better than crash)
    if not width: width = 720
    if not height: height = 576

    # Default to 16-bit (safe fallback for high precision scripts)
    pixel_format = vs_to_ffmpeg_map.get(str(fmt_name).upper(), "yuv420p16le")
    log_info(f"   [INFO] Stream Format: {fmt_name} -> {pixel_format}")

    atempo = _calculate_audio_sync(input_path, duration_sec)

    # Pass temp_output to ffmpeg command
    ffmpeg_cmd = _build_ffmpeg_cmd(input_path, temp_output, atempo, fps=(fps if fps else 29.97), width=width, height=height, pixel_format=pixel_format)

    # vspipe.exe (C++ binary) for raw piping (Fastest) aka "The User Demand"
    # Note: --y4m is NOT supported by all vspipe builds, using raw pipe which is safe now with dynamic format
    vspipe_cmd = [vspipe_exe, str(temp_script), "-"]

    log_debug(f"   [DEBUG] VSPIPE CMD: {vspipe_cmd}")
    log_debug(f"   [DEBUG] FFMPEG CMD: {ffmpeg_cmd}")

    log_info(f"   [INFO] Source Duration: ~{duration_sec / 60:.2f} mins")
    log_info(f">> Encoding to: {output_file.name}")

    success = _run_encoding_pipeline(vspipe_cmd, ffmpeg_cmd, temp_script, duration_sec)

    if success:
        # Atomic Rename
        try:
            if temp_output.exists():
                temp_output.replace(output_file)
        except OSError as e:
            log_error(f"Failed to rename temp output: {e}")

    cleanup_temp_files(work_dir, stem)


def main():
    setup_environment()
    cpu = get_cpu_name()
    gpu = get_gpu_name()
    _show_banner(cpu, gpu, PERF_PROFILE, DEINTERLACE_MODE, ENCODER, HW_SETTINGS)

    check_requirements()

    input_files = get_input_files()
    if not input_files:
        log_info("!! No valid video files found. Exiting.")
        # Only wait if no args (likely double-click)
        if len(sys.argv) == 1:
            input("\nPress Enter to exit...")
        return

    log_info(f"Queue Size: {len(input_files)} videos")

    for i, f in enumerate(input_files):
        log_info(f"\nProcessing {i + 1}/{len(input_files)}...")
        process_video(f)

    log_info("\nAll tasks finished.")
    # Keep window open if double-clicked
    if len(sys.argv) == 1:
        input("\nPress Enter to exit...")


if __name__ == "__main__":
    main()
