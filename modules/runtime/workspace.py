"""Per-video temp workspace used for crash-safe, resumable processing.

Every temp or cache artifact for one input lives inside a single folder next
to the source, ``<input dir>/<file name>.autovhs-tmp/`` (the full name,
extension included, so ``tape.mpg`` and ``tape.mp4`` never share one)::

    restore.vpy            generated VapourSynth script (regenerated each run)
    index/                 source indexes (ffms2 .ffindex, lsmas .lwi, bestsource)
    segments/seg_NNNN.ext  finished video-only segments, safe to reuse
    segments/*.part.*      segment being written, removed at every start
    segments.txt           FFmpeg concat list written right before the mux
    state.json             fingerprint of the settings the segments were made with
    <output>_part.<ext>    muxed result before the atomic rename into place

The folder is removed once the final output is in place, or when a valid
output already exists. It is kept on failure or power loss so the next run
resumes from the last completed segment instead of starting over.
"""

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

WORKSPACE_SUFFIX = ".autovhs-tmp"
STATE_VERSION = 1
# The join stream-copies every segment into the part file, so it needs roughly
# the segments' size again, plus container overhead and the re-encoded audio.
MUX_SPACE_MARGIN = 1.05
# Source identity samples this many chunks of this size spread over the file.
SAMPLE_CHUNK_BYTES = 1024 * 1024
SAMPLE_CHUNKS = 16
MUX_SPACE_MARGIN_BYTES = 256 * 1024 * 1024


@dataclass(frozen=True)
class VideoWorkspace:
    """Resolved paths for one input video's temp workspace."""

    root: Path
    script: Path
    index_dir: Path
    segments_dir: Path
    concat_list: Path
    state_file: Path
    output_part: Path


def get_workspace_root(input_path: Path) -> Path:
    """Return the workspace folder for one input video.

    The full file name is used, not the stem: a folder can legitimately hold
    ``tape.mpg`` and ``tape.mp4``, and keying on the stem alone would give both
    the same workspace, so they would clear each other's segments and state and
    one job's cleanup would delete the other's resume data.
    """
    return input_path.parent / f"{input_path.name}{WORKSPACE_SUFFIX}"


def build_workspace(input_path: Path, output_file: Path) -> VideoWorkspace:
    """Resolve every workspace path without touching the filesystem."""
    root = get_workspace_root(input_path)
    return VideoWorkspace(
        root=root,
        script=root / "restore.vpy",
        index_dir=root / "index",
        segments_dir=root / "segments",
        concat_list=root / "segments.txt",
        state_file=root / "state.json",
        output_part=root / f"{output_file.stem}_part{output_file.suffix}",
    )


def _unlink_quiet(path: Path):
    """Delete a file if present, ignoring filesystem errors."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def remove_partial_files(workspace: VideoWorkspace):
    """Drop everything that was mid-write when the previous run stopped."""
    for partial in workspace.segments_dir.glob("*.part.*"):
        _unlink_quiet(partial)
    _unlink_quiet(workspace.output_part)
    _unlink_quiet(workspace.concat_list)


def prepare_workspace(workspace: VideoWorkspace):
    """Create the workspace layout and remove interrupted partial files."""
    for folder in (workspace.root, workspace.index_dir, workspace.segments_dir):
        folder.mkdir(parents=True, exist_ok=True)
    remove_partial_files(workspace)


def remove_workspace(workspace: VideoWorkspace):
    """Delete the whole workspace folder; nothing outside it is touched."""
    shutil.rmtree(workspace.root, ignore_errors=True)


def _clear_folder(folder: Path):
    """Delete a folder's contents and recreate it, letting failures propagate.

    Failures must not be swallowed here: a segment that survives a failed
    removal would be reused under the *new* fingerprint on the next run, which
    is exactly the mix of old and new content the fingerprint exists to prevent.
    """
    try:
        shutil.rmtree(folder)
    except FileNotFoundError:
        pass
    folder.mkdir(parents=True, exist_ok=True)


def clear_segments(workspace: VideoWorkspace):
    """Discard all segments, used when the settings fingerprint changed."""
    _clear_folder(workspace.segments_dir)


def clear_index(workspace: VideoWorkspace):
    """Discard the source indexes, used when the source file itself changed."""
    _clear_folder(workspace.index_dir)


def _sample_offsets(size: int) -> list[int]:
    """Offsets of the chunks hashed for the identity: the whole file when it is
    at most SAMPLE_CHUNKS chunks long, else SAMPLE_CHUNKS evenly spaced chunks
    with the first at the start of the file and the last ending at its end."""
    if size <= SAMPLE_CHUNK_BYTES * SAMPLE_CHUNKS:
        return list(range(0, size, SAMPLE_CHUNK_BYTES)) or [0]
    step = (size - SAMPLE_CHUNK_BYTES) / (SAMPLE_CHUNKS - 1)
    return [round(index * step) for index in range(SAMPLE_CHUNKS)]


def _sample_digest(input_path: Path, size: int) -> str:
    """Hash evenly spaced samples of the file contents.

    Path, size and mtime cannot tell a source apart from a replacement that
    kept all three (a copy made with preserved timestamps, for instance), and
    reusing segments encoded from the previous content would splice stale
    video into the output. A full digest of a multi-hour capture would read
    tens of gigabytes on every run; sampling reads 16 MiB and still changes
    whenever the content does anywhere near the sampled offsets.
    """
    digest = hashlib.sha256()
    with input_path.open("rb") as handle:
        for offset in _sample_offsets(size):
            handle.seek(offset)
            digest.update(handle.read(SAMPLE_CHUNK_BYTES))
    return digest.hexdigest()


def _source_identity_payload(input_path: Path) -> dict:
    """Describe the source by resolved path, size, nanosecond mtime and content samples."""
    stat_result = input_path.stat()
    size = int(stat_result.st_size)
    return {
        "input": str(input_path.resolve()),
        "size": size,
        # Nanosecond precision: whole seconds would let a source edited inside
        # the same second reuse segments made from the previous content.
        "mtime_ns": int(stat_result.st_mtime_ns),
        "sample_sha256": _sample_digest(input_path, size),
    }


def _sha256_of(payload: dict) -> str:
    """Return a stable hash of a JSON-serialisable mapping."""
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def compute_source_identity(input_path: Path) -> str:
    """Hash the source identity alone, independent of any processing settings."""
    return _sha256_of(_source_identity_payload(input_path))


def compute_fingerprint(input_path: Path, settings: dict) -> str:
    """Hash the source identity plus the settings that shape segment output."""
    return _sha256_of({**_source_identity_payload(input_path), "settings": settings})


def load_state(workspace: VideoWorkspace) -> dict:
    """Read the saved state, returning an empty mapping when absent or corrupt."""
    try:
        loaded = json.loads(workspace.state_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def save_state(workspace: VideoWorkspace, state: dict):
    """Persist the state file atomically so a power cut cannot half-write it."""
    temp_state = workspace.state_file.with_suffix(".json.part")
    temp_state.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    temp_state.replace(workspace.state_file)


def sync_source_identity(workspace: VideoWorkspace, source_id: str) -> bool:
    """Return whether the source file is the one the workspace was built for.

    When it is not, the indexes and segments are dropped *before* anything
    probes the script, so a stale FFMS2 / L-SMASH / BestSource index built
    from the previous file can never feed the metadata probe or a segment.
    """
    state = load_state(workspace)
    if state.get("version") == STATE_VERSION and state.get("source_id") == source_id:
        return True
    clear_index(workspace)
    clear_segments(workspace)
    save_state(workspace, {"version": STATE_VERSION, "source_id": source_id})
    return False


def sync_state(workspace: VideoWorkspace, fingerprint: str) -> bool:
    """Return whether existing segments match the fingerprint; otherwise reset them."""
    state = load_state(workspace)
    if state.get("version") == STATE_VERSION and state.get("fingerprint") == fingerprint:
        return True
    clear_segments(workspace)
    # Keep the source identity recorded by sync_source_identity(); only the
    # settings fingerprint is being replaced here.
    save_state(workspace, {**state, "version": STATE_VERSION, "fingerprint": fingerprint})
    return False


def free_space_bytes(workspace: VideoWorkspace) -> int:
    """Return the free space on the drive that holds the workspace."""
    return shutil.disk_usage(workspace.root).free


def project_output_bytes(first_segment_bytes: int, first_segment_frames: int, total_frames: int | None) -> int | None:
    """Extrapolate the final output size from the first encoded segment.

    A four-hour ProRes tape is a few hundred gigabytes, and during the join
    the segments and the muxed part file coexist, so the caller doubles this
    for the peak. ``None`` means there is not enough information to project.
    """
    if not first_segment_frames or not total_frames:
        return None
    return int(first_segment_bytes * total_frames / first_segment_frames)


def mux_space_needed(segment_files: list[Path]) -> int:
    """Bytes the join needs: a stream copy of every segment plus a small margin."""
    total = sum(path.stat().st_size for path in segment_files if path.exists())
    return int(total * MUX_SPACE_MARGIN) + MUX_SPACE_MARGIN_BYTES


def single_segment_reason(total_frames: int | None, segment_frames: int) -> str | None:
    """Explain why resume is unavailable for a plan, or ``None`` when it is.

    A clip shorter than one segment also yields a single segment, but that
    loses nothing worth warning about, so it is not reported here.
    """
    if not total_frames:
        return "the frame count could not be probed"
    if segment_frames <= 0:
        return "resume_segment_minutes is 0"
    return None


def plan_segments(total_frames: int | None, segment_frames: int) -> list[tuple[int, int | None]]:
    """Split the frame range into ``(start, inclusive_end)`` chunks.

    A single open-ended segment is returned when the frame count is unknown
    or when segmentation is disabled or larger than the clip.
    """
    if not total_frames or segment_frames <= 0 or segment_frames >= total_frames:
        return [(0, None)]
    return [(start, min(start + segment_frames, total_frames) - 1) for start in range(0, total_frames, segment_frames)]


def segment_path(workspace: VideoWorkspace, index: int, extension: str) -> Path:
    """Return the final path of one completed segment."""
    return workspace.segments_dir / f"seg_{index:04d}{extension}"


def segment_part_path(workspace: VideoWorkspace, index: int, extension: str) -> Path:
    """Return the in-progress path of one segment while FFmpeg writes it."""
    return workspace.segments_dir / f"seg_{index:04d}.part{extension}"


def _concat_escape(path: Path) -> str:
    """Escape a path for the FFmpeg concat demuxer single-quoted syntax."""
    return str(path.resolve()).replace("\\", "/").replace("'", "'\\''")


def write_concat_list(workspace: VideoWorkspace, segment_files: list[Path]):
    """Write the FFmpeg concat demuxer list for the finished segments."""
    lines = ["ffconcat version 1.0"] + [f"file '{_concat_escape(path)}'" for path in segment_files]
    workspace.concat_list.write_text("\n".join(lines) + "\n", encoding="utf-8")


__all__ = [
    "WORKSPACE_SUFFIX",
    "VideoWorkspace",
    "get_workspace_root",
    "build_workspace",
    "prepare_workspace",
    "remove_partial_files",
    "remove_workspace",
    "clear_segments",
    "clear_index",
    "compute_source_identity",
    "compute_fingerprint",
    "load_state",
    "save_state",
    "sync_source_identity",
    "sync_state",
    "plan_segments",
    "free_space_bytes",
    "project_output_bytes",
    "mux_space_needed",
    "single_segment_reason",
    "segment_path",
    "segment_part_path",
    "write_concat_list",
]
