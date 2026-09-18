"""Input discovery: CLI arguments, folder scans, and the interactive prompt."""

import sys
from pathlib import Path

from modules.core.config import CONFIG
from modules.core.utils import log_debug, log_info

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".ts", ".m2ts", ".mpg", ".mpeg"}
_LEGACY_OUTPUT_TOKENS = ("_deinterlaced", "_intermediate")


def _excluded_name_tokens() -> tuple[str, ...]:
    """Name fragments that mark a file as one of our own outputs.

    The configured ``output_suffix`` values are included, not just the historic
    defaults: with a custom suffix such as ``_restored`` a folder scan would
    otherwise queue a finished output and deinterlace it a second time.
    """
    configured = (
        CONFIG.get("output_suffix", "_deinterlaced_prores"),
        CONFIG.get("output_suffix_av1", "_deinterlaced_av1"),
    )
    return _LEGACY_OUTPUT_TOKENS + tuple(token for token in configured if isinstance(token, str) and token)


def _is_candidate_video(path: Path, video_exts: set) -> bool:
    """Return whether a path is an unprocessed video file input."""
    if not path.is_file() or path.suffix.lower() not in video_exts:
        return False
    return not any(token in path.name for token in _excluded_name_tokens())


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


def _print_interactive_help():
    """Print the interactive usage prompt."""
    print("\n" + "-" * 60)
    print(" [HOW TO USE]")
    print(" 1. Drag and Drop a video file (or folder) onto this window.")
    print(" 2. Or paste the file path below.")
    print("-" * 60 + "\n")


def _strip_wrapping_quotes(value: str) -> str:
    """Remove a matching pair of surrounding quotes and unescape spaces from a user-supplied path."""
    cleaned = value.strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in ('"', "'"):
        cleaned = cleaned[1:-1]
    if sys.platform != "win32":
        cleaned = cleaned.replace("\\ ", " ")
    return cleaned


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
    except (EOFError, KeyboardInterrupt):
        log_info("\n>> Interactive input cancelled. Exiting.")
    return []


def get_input_files():
    """Gathers input files from CLI args or interactive prompt."""
    # 1. Drag & Drop (CLI Args)
    files = _parse_cli_args(VIDEO_EXTENSIONS)

    # 2. Interactive Prompt
    if not files:
        files = _get_interactive_input(VIDEO_EXTENSIONS)

    return files


__all__ = [
    "VIDEO_EXTENSIONS",
    "get_input_files",
]
