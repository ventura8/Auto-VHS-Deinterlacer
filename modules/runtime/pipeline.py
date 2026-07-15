"""Main video processing pipeline for deinterlacing and encoding.

Architecture notes
------------------
This module intentionally keeps the end-to-end orchestration logic close together
so operators can debug a failed job from one place. The tradeoff is file size,
so this header documents key invariants and execution phases that must remain
stable during future refactors.

Execution phases
----------------
1. Input discovery:
    - Resolve drag-and-drop paths and optional folder scans.
    - Ignore already-processed filenames by suffix markers.
2. Pre-flight preparation:
    - Build deterministic output path from encoder + config suffix policy.
    - Clean stale temp/index artifacts before script generation.
    - Skip processing if a valid output already exists.
3. Script + metadata stage:
    - Generate VPY script with runtime profile settings.
    - Probe VPY output with vspipe for frame count, FPS, and pixel format.
4. Encoding stage:
    - Stream VapourSynth frames directly to FFmpeg in one pass.
    - Preserve source audio and apply optional drift correction filters.
    - Track progress, ETA, and speed from FFmpeg stderr.
5. Finalization:
    - Emit an explicit final 100 percent progress update on success.
    - Atomically rename part output to final output filename.
    - Always perform robust temp file cleanup.

Operational invariants
----------------------
- Progress reporting must never regress from 100 percent after success.
- Existing valid outputs must be skipped, not overwritten.
- Corrupted existing outputs (zero duration) may be replaced.
- Temp script and transient index artifacts are cleanup targets.
- FFmpeg command must always map video from pipe and audio from source.
- Audio drift correction remains bounded by safety thresholds from config.
- Duration fallback must tolerate missing VPY frame metadata.
- Pixel format fallback must remain conservative and encoder-safe.

Patchability guarantees for tests
---------------------------------
Many tests patch symbols in this module directly. Keep that behavior stable:
- `get_duration`, `create_vpy_script`, `get_vpy_info`, `cleanup_temp_files`
  are patch targets in integration tests.
- `_run_encoding_pipeline` and `_build_ffmpeg_cmd` are called directly in tests.
- `setup_environment`, `check_requirements`, and `get_input_files` are patched
  around `main()` to isolate orchestration behavior.

Error-handling contract
-----------------------
- Hard failures in subprocess setup should be logged and returned as failed
  processing results, not raised to crash batch processing.
- Batch loop failures should continue to next item after logging.
- Interactive no-input flows should print guidance and allow graceful exit.

Why comments are explicit here
------------------------------
This file coordinates user input, subprocess piping, metadata probing, and
batch accounting. Dense inline documentation helps preserve intent when tuning
hardware profiles, changing encoder arguments, or evolving progress parsing.
"""

import io
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from modules.core.config import (
    AUDIO_BITRATE,
    AUDIO_CODEC,
    AUDIO_OFFSET,
    CONFIG,
    DEBUG_MODE,
    DEINTERLACE_MODE,
    ENCODER,
    HW_SETTINGS,
    PERF_PROFILE,
)
from modules.core.utils import (
    _show_banner,
    check_requirements,
    cleanup_temp_files,
    get_cpu_name,
    get_duration,
    get_gpu_name,
    get_vspipe_env,
    is_python_vspipe_launcher,
    log_debug,
    log_error,
    log_info,
    parse_ffmpeg_time,
    setup_environment,
    update_progress,
)
from modules.runtime.vspipe import create_vpy_script, get_vpy_info, log_vspipe_output, resolve_vspipe_requests

# ==============================================================================
# MAIN PIPELINE
# ==============================================================================

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".ts", ".m2ts", ".mpg", ".mpeg"}
VS_TO_FFMPEG_MAP = {
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
    "YUV444P16": "yuv444p16le",
}


def _get_vspipe_requests() -> int:
    """Resolve vspipe request depth from config, defaulting to cpu_threads."""
    return resolve_vspipe_requests(CONFIG, HW_SETTINGS)


def _is_candidate_video(path: Path, video_exts: set) -> bool:
    """Return whether a path is an unprocessed video file input."""
    excluded_tokens = ("_deinterlaced", "_intermediate")
    return path.is_file() and path.suffix.lower() in video_exts and not any(token in path.name for token in excluded_tokens)


def _scan_directory(path: Path, video_exts: set) -> list:
    """Scans a directory for video files, excluding processed ones."""
    log_info(f">> Scanning folder: {path.name}")
    return [file_path for file_path in path.iterdir() if _is_candidate_video(file_path, video_exts)]


def _append_cli_path(files: list[Path], path: Path, video_exts: set):
    """Append inputs derived from one CLI path argument."""
    if _is_candidate_video(path, video_exts):
        files.append(path)
        return
    if path.is_dir():
        files.extend(_scan_directory(path, video_exts))


def _parse_cli_args(video_exts: set) -> list:
    """Parses command line arguments for input files or folders."""
    files = []
    if len(sys.argv) > 1:
        log_info(f">> Arguments Detected: {len(sys.argv) - 1} items")
        for arg in sys.argv[1:]:
            _append_cli_path(files, Path(arg), video_exts)
    return files


def _get_audio_sync_skip_reason(audio_duration: float, video_duration: float, abs_diff: float) -> str | None:
    """Return a log message explaining why drift correction should be skipped."""
    if not CONFIG.get("auto_drift_correction", True):
        return "   [SYNC] Auto-drift correction disabled by config."

    min_drift = CONFIG.get("audio_drift_min_seconds", 0.05)
    if abs_diff <= min_drift:
        return f"   [SYNC] Perfect Sync (Drift: {abs_diff:.3f}s). No correction needed."

    if audio_duration < video_duration:
        return f"   [SYNC] Audio is shorter than video by {abs_diff:.3f}s. Ignoring."
    if video_duration <= 0:
        return "   [SYNC] Video duration is zero. Ignoring safely."

    return _get_excessive_drift_message(video_duration, abs_diff)


def _get_excessive_drift_message(video_duration: float, abs_diff: float) -> str | None:
    """Return a skip message when the drift percentage exceeds the configured limit."""

    max_drift_pct = CONFIG.get("audio_drift_max_percent", 0.5)
    drift_pct = (abs_diff / video_duration) * 100
    if drift_pct > max_drift_pct:
        return f"   [SYNC] Drift too large ({drift_pct:.2f}% / {abs_diff:.3f}s). Ignoring safely."
    return None


def _print_interactive_help():
    """Print the interactive usage prompt."""
    print("\n" + "-" * 60)
    print(" [HOW TO USE]")
    print(" 1. Drag and Drop a video file (or folder) onto this window.")
    print(" 2. Or paste the file path below.")
    print("-" * 60 + "\n")


def _strip_wrapping_quotes(value: str) -> str:
    """Remove a matching pair of surrounding quotes from a user-supplied path."""
    for quote_char in ('"', "'"):
        if value.startswith(quote_char) and value.endswith(quote_char):
            return value[1:-1]
    return value


def _expand_input_path(path: Path, video_exts: set) -> list[Path]:
    """Expand a file or directory argument into input video paths."""
    if path.is_file():
        return [path] if _is_candidate_video(path, video_exts) else []
    if path.is_dir():
        return _scan_directory(path, video_exts)
    return []


def _get_default_input_files(video_exts: set) -> list[Path]:
    """Fallback to scanning the default input directory when no input was entered."""
    default_input = Path("input")
    if default_input.exists() and default_input.is_dir():
        log_info(">> No input provided. Auto-scanning 'input' folder...")
        return _scan_directory(default_input, video_exts)
    return []


def _get_interactive_input(video_exts: set) -> list:
    """Gets input files from interactive user prompt."""
    try:
        _print_interactive_help()
        user_input = input(">> Please Drag & Drop a video file here and press Enter: ").strip()
        log_debug(f"User Input: {user_input}")
        if not user_input:
            return _get_default_input_files(video_exts)

        cleaned_input = _strip_wrapping_quotes(user_input)
        path = Path(cleaned_input)
        if path.exists():
            return _expand_input_path(path, video_exts)
    except KeyboardInterrupt:
        pass
    return []


def get_input_files():
    """Gathers input files from CLI args or interactive prompt."""
    # 1. Drag & Drop (CLI Args)
    files = _parse_cli_args(VIDEO_EXTENSIONS)

    # 2. Interactive Prompt
    if not files:
        files = _get_interactive_input(VIDEO_EXTENSIONS)

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
    abs_diff = abs(audio_duration - video_duration)
    skip_reason = _get_audio_sync_skip_reason(audio_duration, video_duration, abs_diff)
    if skip_reason:
        log_info(skip_reason)
        return 1.0

    log_info(f"   [SYNC] Correction needed: {abs_diff:.3f}s drift detected.")
    if video_duration <= 0:
        return 1.0
    return audio_duration / video_duration


def _get_video_encoder_args(ffmpeg_threads: int, hardware_settings: dict) -> list[str]:
    """Return the configured FFmpeg video encoder argument list."""
    if ENCODER == "prores":
        return [
            "-c:v",
            "prores_ks",
            "-profile:v",
            "3",
            "-vendor",
            "apl0",
            "-bits_per_mb",
            "8000",
            "-pix_fmt",
            "yuv422p10le",
        ]
    if hardware_settings.get("has_av1_nvenc", False):
        return [
            "-c:v",
            "av1_nvenc",
            "-preset",
            "p5",
            "-cq",
            "22",
            "-b:v",
            "0",
            "-pix_fmt",
            "p010le",
        ]
    return [
        "-c:v",
        "libsvtav1",
        "-preset",
        "6",
        "-crf",
        "22",
        "-pix_fmt",
        "yuv420p10le",
        "-svtav1-params",
        f"lp={ffmpeg_threads}",
    ]


def _log_encoder_execution_path(hardware_settings: dict):
    """Log whether the active video encoder path is GPU or CPU based."""
    if ENCODER == "av1":
        if hardware_settings.get("has_av1_nvenc", False):
            log_info("   [ENCODER] AV1 path: NVIDIA GPU enabled (av1_nvenc).")
            return
        log_info("   [ENCODER] AV1 path: CPU fallback enabled (libsvtav1).")
        return

    log_info("   [ENCODER] ProRes path: CPU encoder enabled (prores_ks).")


def _get_audio_filter_args(atempo: float) -> list[str]:
    """Return optional FFmpeg audio filter arguments."""
    audio_filters = []
    if atempo != 1.0:
        audio_filters.append(f"atempo={atempo:.6f}")
    if AUDIO_OFFSET != 0:
        delay_ms = int(AUDIO_OFFSET * 1000)
        audio_filters.append(f"adelay={delay_ms}|{delay_ms}")
    if not audio_filters:
        return []
    return ["-af", ",".join(audio_filters)]


def _build_ffmpeg_cmd(
    input_path: Path,
    output_file: Path,
    atempo: float,
    fps: float = 30000 / 1001,
    width: int = 720,
    height: int = 576,
    pixel_format: str = "yuv420p16le",
) -> list:
    """Builds the FFmpeg command line."""
    ffmpeg_exe = shutil.which("ffmpeg") or "ffmpeg"
    ffmpeg_threads = max(1, int(HW_SETTINGS.get("cpu_threads", os.cpu_count() or 8)))
    cmd = [
        ffmpeg_exe,
        "-y",
        "-f",
        "rawvideo",
        "-vcodec",
        "rawvideo",
        "-s",
        f"{width}x{height}",
        "-r",
        str(fps),
        "-pix_fmt",
        pixel_format,
        "-i",
        "-",
        "-i",
        str(input_path),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
    ]
    cmd.extend(["-threads:v", str(ffmpeg_threads)])
    _log_encoder_execution_path(HW_SETTINGS)
    cmd.extend(_get_video_encoder_args(ffmpeg_threads, HW_SETTINGS))
    cmd.extend(_get_audio_filter_args(atempo))
    cmd.extend(["-c:a", AUDIO_CODEC, "-b:a", str(AUDIO_BITRATE), str(output_file)])
    return cmd


def _format_total_timestamp(duration_sec: float) -> str | None:
    """Convert total video seconds into the display timestamp format used by progress updates."""
    if duration_sec <= 0:
        return None

    total_ms = int(round(duration_sec * 1000))
    th, rem_ms = divmod(total_ms, 3600000)
    tm, rem_ms = divmod(rem_ms, 60000)
    ts_int, ms_int = divmod(rem_ms, 1000)
    return f"{th:02d}:{tm:02d}:{ts_int:02d},{ms_int:03d}"


def _prepare_vspipe_env(vspipe_cmd: list[str]) -> dict[str, str]:
    """Prepare the subprocess environment for vspipe execution."""
    vspipe_env = get_vspipe_env()
    if vspipe_cmd and (vspipe_cmd[0] == sys.executable or is_python_vspipe_launcher(vspipe_cmd[0])):
        vspipe_env.pop("PYTHONHOME", None)
        vspipe_env.pop("PYTHONPATH", None)
    return vspipe_env


def _format_eta(speed: str | None, duration_sec: float, current_sec: float) -> str:
    """Estimate remaining wall-clock time from FFmpeg speed output."""
    if not speed:
        return "--:--:--"

    try:
        speed_val = float(speed.replace("x", ""))
    except ValueError:
        return "--:--:--"

    if speed_val <= 0:
        return "--:--:--"

    remaining_video_sec = max(0.0, duration_sec - current_sec)
    remaining_real_sec = remaining_video_sec / speed_val
    m, s = divmod(int(remaining_real_sec), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _update_encoding_progress(line_str: str, duration_sec: float, total_ts: str | None):
    """Parse and forward FFmpeg progress updates."""
    if "frame=" not in line_str:
        return

    sec, current_ts, speed = parse_ffmpeg_time(line_str)
    if not sec or duration_sec <= 0:
        return

    pct = (sec / duration_sec) * 100
    eta_str = _format_eta(speed, duration_sec, sec)
    time_display = f"{current_ts} / {total_ts or '00:00:00,000'}"
    update_progress(pct, "Encoding", time_display, speed, eta_str, process_name="FFmpeg")


def _read_ffmpeg_stderr(stderr_pipe, duration_sec: float, total_ts: str | None) -> list[str]:
    """Capture recent FFmpeg stderr lines while emitting progress updates."""
    stderr_lines: list[str] = []
    if not stderr_pipe:
        return stderr_lines

    stderr_reader = io.TextIOWrapper(stderr_pipe, encoding="utf-8", errors="replace")
    for line in stderr_reader:
        line_str = line.strip()
        stderr_lines.append(line_str)
        if len(stderr_lines) > 20:
            stderr_lines.pop(0)
        _update_encoding_progress(line_str, duration_sec, total_ts)

    return stderr_lines


def _finalize_encoding_success(temp_script: Path, total_ts: str | None):
    """Emit final success progress and clean up the temporary script."""
    if total_ts:
        final_time = f"{total_ts} / {total_ts}"
        update_progress(100.0, "Encoding", final_time, None, "00:00:00", process_name="FFmpeg")
    else:
        update_progress(100.0, "Encoding", process_name="FFmpeg")

    log_info("\n\n[SUCCESS] Deinterlacing finished.")
    if temp_script.exists():
        try:
            os.remove(temp_script)
        except OSError:
            pass


def _log_ffmpeg_failure(returncode: int | None, stderr_lines: list[str]):
    """Report FFmpeg failure details using the captured stderr tail."""
    log_error(f"\n[ERROR] FFmpeg failed with exit code {returncode}")
    log_error(">> Last 20 lines of FFmpeg Error Log:")
    for err_line in stderr_lines:
        log_error(f"   {err_line}")


def _collect_pipeline_stderr(p_vspipe, p_ffmpeg, duration_sec: float, total_ts: str | None) -> list[str]:
    """Stream vspipe logs, collect FFmpeg stderr, and wait for both processes."""
    if p_vspipe.stdout:
        p_vspipe.stdout.close()

    t_vspipe = threading.Thread(target=log_vspipe_output, args=(p_vspipe.stderr,))
    t_vspipe.daemon = True
    t_vspipe.start()
    stderr_lines = _read_ffmpeg_stderr(p_ffmpeg.stderr, duration_sec, total_ts)

    p_ffmpeg.wait()
    p_vspipe.wait()
    return stderr_lines


def _pipeline_succeeded(p_ffmpeg, p_vspipe) -> bool:
    """Return whether both pipeline processes exited successfully."""
    return p_ffmpeg.returncode == 0 and p_vspipe.returncode == 0


def _get_pipeline_failure_code(p_ffmpeg, p_vspipe) -> int | None:
    """Prefer the FFmpeg failure code, otherwise fall back to vspipe."""
    return p_ffmpeg.returncode if p_ffmpeg.returncode != 0 else p_vspipe.returncode


def _run_encoding_pipeline(vspipe_cmd, ffmpeg_cmd, duration_sec):
    """Executes the VS->FFmpeg pipeline and monitors progress."""
    try:
        total_ts = _format_total_timestamp(duration_sec)
        vspipe_env = _prepare_vspipe_env(vspipe_cmd)

        with subprocess.Popen(vspipe_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=vspipe_env) as p_vspipe:
            with subprocess.Popen(
                ffmpeg_cmd,
                stdin=p_vspipe.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            ) as p_ffmpeg:
                stderr_lines = _collect_pipeline_stderr(p_vspipe, p_ffmpeg, duration_sec, total_ts)

        if _pipeline_succeeded(p_ffmpeg, p_vspipe):
            return True
        failed_returncode = _get_pipeline_failure_code(p_ffmpeg, p_vspipe)
        _log_ffmpeg_failure(failed_returncode, stderr_lines)
        return False

    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        log_error(f"Unexpected error during processing: {error}")
        return False


def _format_elapsed(seconds: float) -> str:
    """Format elapsed seconds as HH:MM:SS."""
    total_seconds = max(0, int(seconds))
    h, rem = divmod(total_seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _format_speed(speed_x: float | None) -> str:
    """Format an effective pipeline speed multiplier."""
    if speed_x is None or speed_x <= 0:
        return "N/A"
    return f"{speed_x:.2f}x"


def _log_video_summary(input_path: Path, started_at: float, status: str, output_path: Path | None = None, speed_x: float | None = None):
    """Log a single-video processing summary block."""
    elapsed = _format_elapsed(time.time() - started_at)
    log_info("\n[VIDEO SUMMARY]")
    log_info(f"   Input   : {input_path.name}")
    if output_path:
        log_info(f"   Output  : {output_path.name}")
    log_info(f"   Status  : {status.upper()}")
    log_info(f"   Elapsed : {elapsed}")
    log_info(f"   Speed   : {_format_speed(speed_x)}")


def _build_result(
    input_path: Path,
    output_path: Path | None,
    status: str,
    elapsed_sec: float,
    duration_sec: float = 0.0,
    speed_x: float | None = None,
) -> dict:
    """Create the standard result payload returned by process_video."""
    return {
        "input": input_path,
        "output": output_path,
        "status": status,
        "elapsed_sec": elapsed_sec,
        "duration_sec": duration_sec,
        "speed_x": speed_x,
    }


def _get_existing_output_result(input_path: Path, output_file: Path, started_at: float, work_dir: Path, stem: str) -> dict | None:
    """Return a skip result when a valid output already exists."""
    if not output_file.exists():
        return None

    existing_duration = get_duration(str(output_file))
    if existing_duration > 0:
        log_info(f"   [SKIP] Output exists and valid: {output_file.name}")
        cleanup_temp_files(work_dir, stem)
        _log_video_summary(input_path, started_at, "skipped", output_file)
        return _build_result(input_path, output_file, "skipped", time.time() - started_at)

    log_info(f"   [WARNING] Output exists but seems corrupted (0 duration). Overwriting: {output_file.name}")
    return None


def _resolve_dimensions(width: int | None, height: int | None) -> tuple[int, int]:
    """Apply safe fallback dimensions when vspipe metadata is incomplete."""
    return width or 720, height or 576


def _resolve_pixel_format(fmt_name) -> str:
    """Map VapourSynth format names to FFmpeg pixel formats."""
    return VS_TO_FFMPEG_MAP.get(str(fmt_name).upper(), "yuv420p16le")


def _rename_completed_output(temp_output: Path, output_file: Path) -> bool:
    """Atomically replace the final output with the completed temp file."""
    if not temp_output.exists():
        log_error(f"Failed to rename temp output: missing temp file {temp_output}")
        return False

    try:
        temp_output.replace(output_file)
        return True
    except OSError as error:
        log_error(f"Failed to rename temp output: {error}")
        return False


def _build_missing_input_result(input_path: Path, started_at: float) -> dict:
    """Return the standardized result for a missing input path."""
    log_error(f"Input not found: {input_path}")
    _log_video_summary(input_path, started_at, "not found")
    return _build_result(input_path, None, "not_found", time.time() - started_at)


def _prepare_processing_paths(input_path: Path) -> tuple[Path, str, Path, Path, Path]:
    """Return the working paths used by one processing job."""
    work_dir = input_path.parent
    stem = input_path.stem
    output_file = _get_output_path(input_path)
    temp_script = work_dir / f"{stem}_temp_script.vpy"
    temp_output = output_file.with_name(f"{output_file.stem}_part{output_file.suffix}")
    return work_dir, stem, output_file, temp_script, temp_output


def _finalize_processing_result(
    input_path: Path,
    output_file: Path,
    started_at: float,
    duration_sec: float,
    success: bool,
    rename_success: bool,
) -> dict:
    """Build and log the final process result payload."""
    elapsed_sec = time.time() - started_at
    speed_x = _get_speed_multiplier(duration_sec, elapsed_sec)
    final_success = success and rename_success
    final_status = _get_processing_status(final_success)
    final_output = output_file if final_success and output_file.exists() else None
    _log_video_summary(input_path, started_at, final_status, final_output, speed_x)
    return _build_result(input_path, final_output, final_status, elapsed_sec, duration_sec, speed_x)


def _build_processing_commands(input_path: Path, temp_script: Path, temp_output: Path):
    """Generate metadata and commands needed for a single encoding run."""
    log_info(">> Generating VapourSynth Restoration Script...")
    create_vpy_script(str(input_path), str(temp_script), DEINTERLACE_MODE)

    log_info(">> Verifying Script with vspipe...")
    vspipe_exe = shutil.which("vspipe") or "vspipe"
    total_frames, fps, width, height, fmt_name = get_vpy_info(vspipe_exe, str(temp_script))
    duration_sec = total_frames / (fps if fps else 29.97) if total_frames else get_duration(str(input_path))
    safe_width, safe_height = _resolve_dimensions(width, height)
    pixel_format = _resolve_pixel_format(fmt_name)
    log_info(f"   [INFO] Stream Format: {fmt_name} -> {pixel_format}")

    atempo = _calculate_audio_sync(input_path, duration_sec)
    ffmpeg_cmd = _build_ffmpeg_cmd(
        input_path,
        temp_output,
        atempo,
        fps=(fps if fps else 29.97),
        width=safe_width,
        height=safe_height,
        pixel_format=pixel_format,
    )
    vspipe_requests = _get_vspipe_requests()
    log_info(f"   [VSPIPE] requests={vspipe_requests}")
    vspipe_cmd = [vspipe_exe, "--requests", str(vspipe_requests), str(temp_script), "-"]
    log_info(f"   [VSPIPE CMD] {' '.join(vspipe_cmd)}")
    return duration_sec, ffmpeg_cmd, vspipe_cmd


def process_video(input_path: Path):
    """Refined processing pipeline with restart handling and robust piping."""
    started_at = time.time()

    _set_runtime_log_level()

    if not input_path.exists():
        return _build_missing_input_result(input_path, started_at)

    log_info(f"\n[JOB START] Processing: {input_path.name}")
    log_info("-" * 40)

    work_dir, stem, output_file, temp_script, temp_output = _prepare_processing_paths(input_path)
    cleanup_temp_files(work_dir, stem)
    existing_output_result = _get_existing_output_result(input_path, output_file, started_at, work_dir, stem)
    if existing_output_result is not None:
        return existing_output_result

    duration_sec, ffmpeg_cmd, vspipe_cmd = _build_processing_commands(input_path, temp_script, temp_output)

    log_debug(f"   [DEBUG] VSPIPE CMD: {vspipe_cmd}")
    log_debug(f"   [DEBUG] FFMPEG CMD: {ffmpeg_cmd}")

    log_info(f"   [INFO] Source Duration: ~{duration_sec / 60:.2f} mins")
    log_info(f">> Encoding to: {output_file.name}")

    success = _run_encoding_pipeline(vspipe_cmd, ffmpeg_cmd, duration_sec)

    rename_success = True
    if success:
        rename_success = _rename_completed_output(temp_output, output_file)
        if rename_success:
            _finalize_encoding_success(temp_script, _format_total_timestamp(duration_sec))

    cleanup_temp_files(work_dir, stem)
    return _finalize_processing_result(input_path, output_file, started_at, duration_sec, success, rename_success)


def _set_runtime_log_level():
    """Set the pipeline logger level based on debug mode."""
    logging.getLogger("AutoVHS").setLevel(logging.DEBUG if DEBUG_MODE else logging.INFO)


def _get_processing_status(success: bool) -> str:
    """Return the canonical status label for a processing result."""
    return "success" if success else "failed"


def _get_speed_multiplier(duration_sec: float, elapsed_sec: float) -> float | None:
    """Return effective processing speed when both durations are positive."""
    if elapsed_sec <= 0 or duration_sec <= 0:
        return None
    return duration_sec / elapsed_sec


def _prompt_before_exit_if_interactive():
    """Keep the console window open for double-click launches."""
    if len(sys.argv) == 1:
        input("\nPress Enter to exit...")


def _log_batch_result(index: int, total: int):
    """Log progress before processing the next queued video."""
    log_info(f"\nProcessing {index}/{total}...")


def _process_batch(input_files: list[Path]) -> list[dict]:
    """Process each queued file and collect successful result payloads."""
    results = []
    for index, input_file in enumerate(input_files, start=1):
        _log_batch_result(index, len(input_files))
        started_at = time.time()
        try:
            result = process_video(input_file)
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
            log_error(f"[ERROR] Failed processing {input_file}: {error}")
            results.append(_build_result(input_file, None, "failed", time.time() - started_at))
            continue
        if result:
            results.append(result)
    return results


def _get_batch_counts(results: list[dict]) -> tuple[int, int, int]:
    """Count success, skipped, and failed results for the batch summary."""
    success_count = 0
    skipped_count = 0
    failed_count = 0
    for result in results:
        status = result.get("status")
        if status == "success":
            success_count += 1
        elif status == "skipped":
            skipped_count += 1
        elif status in {"failed", "not_found"}:
            failed_count += 1
    return success_count, skipped_count, failed_count


def _has_speed_metrics(result: dict) -> bool:
    """Return whether a result can contribute to aggregate batch speed."""
    return result.get("status") == "success" and (result.get("duration_sec") or 0) > 0 and (result.get("elapsed_sec") or 0) > 0


def _get_speed_rows(results: list[dict]) -> list[dict]:
    """Select results that can contribute to an aggregate batch speed."""
    speed_rows = []
    for result in results:
        if _has_speed_metrics(result):
            speed_rows.append(result)
    return speed_rows


def _format_batch_speed(batch_speed: float | None) -> str:
    """Format the aggregate batch speed value for summary output."""
    return f"{batch_speed:.2f}x" if batch_speed and batch_speed > 0 else "N/A"


def _format_batch_result_row(result: dict) -> str:
    """Format one result row for the batch summary output."""
    input_name = result.get("input").name if result.get("input") else "unknown"
    output_obj = result.get("output")
    output_name = output_obj.name if output_obj else "-"
    status_text = str(result.get("status", "unknown")).upper()
    speed_text = _format_speed(result.get("speed_x"))
    return f"     - {input_name} -> {status_text} (speed: {speed_text}, output: {output_name})"


def _log_batch_video_rows(results: list[dict]):
    """Emit one summary row per processed video."""
    log_info("   Videos  :")
    for result in results:
        log_info(_format_batch_result_row(result))


def _calculate_batch_speed(speed_rows: list[dict]) -> float | None:
    """Calculate aggregate throughput for successful results."""
    total_src_sec = 0.0
    total_elapsed_sec = 0.0
    for result in speed_rows:
        total_src_sec += float(result.get("duration_sec") or 0.0)
        total_elapsed_sec += float(result.get("elapsed_sec") or 0.0)
    if total_elapsed_sec <= 0:
        return None
    return total_src_sec / total_elapsed_sec


def _log_batch_summary(input_files: list[Path], results: list[dict], batch_started_at: float):
    """Log the aggregate summary for multi-video runs."""
    if len(input_files) <= 1:
        return

    success_count, skipped_count, failed_count = _get_batch_counts(results)
    batch_speed = _calculate_batch_speed(_get_speed_rows(results))

    log_info("\n[BATCH SUMMARY]")
    log_info(f"   Total   : {len(input_files)}")
    log_info(f"   Success : {success_count}")
    log_info(f"   Skipped : {skipped_count}")
    log_info(f"   Failed  : {failed_count}")
    log_info(f"   Elapsed : {_format_elapsed(time.time() - batch_started_at)}")
    log_info(f"   Speed   : {_format_batch_speed(batch_speed)}")
    _log_batch_video_rows(results)


def _run_preflight():
    """Initialize the runtime environment and print the startup banner."""
    setup_environment()
    cpu = get_cpu_name()
    gpu = get_gpu_name()
    _show_banner(cpu, gpu, PERF_PROFILE, DEINTERLACE_MODE, ENCODER, HW_SETTINGS)
    check_requirements()


def _get_or_prompt_input_files() -> list[Path]:
    """Collect input files and handle the no-input exit path."""
    input_files = get_input_files()
    if input_files:
        return input_files

    log_info("!! No valid video files found. Exiting.")
    _prompt_before_exit_if_interactive()
    return []


def main():
    """Run preflight checks, gather inputs, and process queued files."""
    batch_started_at = time.time()

    _run_preflight()
    input_files = _get_or_prompt_input_files()
    if not input_files:
        return

    log_info(f"Queue Size: {len(input_files)} videos")

    results = _process_batch(input_files)

    log_info("\nAll tasks finished.")
    _log_batch_summary(input_files, results, batch_started_at)
    _prompt_before_exit_if_interactive()


__all__ = [
    "get_input_files",
    "process_video",
    "main",
    "Path",
]


if __name__ == "__main__":
    main()
