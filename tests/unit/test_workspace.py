"""Unit tests for the per-video temp workspace helpers."""

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from modules.runtime import workspace as ws_module

# Module-private helper, bound the way the rest of the suite binds them.
_unlink_quiet = getattr(ws_module, "_unlink_quiet")


def _make_workspace(tmp_path: Path) -> ws_module.VideoWorkspace:
    """Build a workspace for a fake input inside ``tmp_path``."""
    input_path = tmp_path / "tape.mpg"
    input_path.write_bytes(b"source")
    return ws_module.build_workspace(input_path, tmp_path / "tape_deinterlaced_prores.mov")


def test_build_workspace_keeps_everything_under_one_folder(tmp_path):
    """Every workspace path must live inside ``<file name>.autovhs-tmp`` beside the source."""
    workspace = _make_workspace(tmp_path)
    root = tmp_path / "tape.mpg.autovhs-tmp"

    assert workspace.root == root == ws_module.get_workspace_root(tmp_path / "tape.mpg")
    members = (workspace.script, workspace.index_dir, workspace.segments_dir)
    members += (workspace.concat_list, workspace.state_file, workspace.output_part)
    assert all(root in path.parents for path in members)
    assert workspace.output_part.name == "tape_deinterlaced_prores_part.mov"


def _workspace_for_name(tmp_path: Path, name: str) -> ws_module.VideoWorkspace:
    """Create one source file and resolve its workspace."""
    source = tmp_path / name
    source.write_bytes(b"source")
    return ws_module.build_workspace(source, tmp_path / "tape_deinterlaced_prores.mov")


def _same_stem_workspaces(tmp_path: Path) -> tuple[ws_module.VideoWorkspace, ws_module.VideoWorkspace]:
    """Build workspaces for two sources that differ only by extension."""
    return _workspace_for_name(tmp_path, "tape.mpg"), _workspace_for_name(tmp_path, "tape.mp4")


def _workspace_paths(workspace) -> set:
    """Every path one job may write inside its workspace."""
    return {workspace.root, workspace.script, workspace.index_dir, workspace.segments_dir, workspace.state_file, workspace.output_part}


def test_same_stem_sources_get_separate_workspaces(tmp_path):
    """``tape.mpg`` and ``tape.mp4`` in one folder must not share any path.

    Keying on the stem alone gave both the same folder, so each run cleared the
    other's segments and one job's cleanup deleted the other's resume state.
    """
    mpg_ws, mp4_ws = _same_stem_workspaces(tmp_path)

    assert mpg_ws.root.name == "tape.mpg.autovhs-tmp"
    assert mp4_ws.root.name == "tape.mp4.autovhs-tmp"
    assert not _workspace_paths(mpg_ws) & _workspace_paths(mp4_ws)


def test_removing_one_workspace_keeps_the_other_resume_state(tmp_path):
    """Finishing one same-stem job must not delete the other job's resume state."""
    mpg_ws, mp4_ws = _same_stem_workspaces(tmp_path)
    ws_module.prepare_workspace(mpg_ws)
    ws_module.prepare_workspace(mp4_ws)
    ws_module.save_state(mp4_ws, {"version": ws_module.STATE_VERSION, "fingerprint": "fp"})

    ws_module.remove_workspace(mpg_ws)

    assert not mpg_ws.root.exists()
    assert ws_module.load_state(mp4_ws)["fingerprint"] == "fp"


def test_prepare_workspace_creates_layout_and_removes_partials(tmp_path):
    """Preparing the workspace drops interrupted files but keeps finished segments."""
    workspace = _make_workspace(tmp_path)
    ws_module.prepare_workspace(workspace)
    finished = ws_module.segment_path(workspace, 0, ".mov")
    finished.write_bytes(b"done")
    partial = ws_module.segment_part_path(workspace, 1, ".mov")
    partial.write_bytes(b"half")
    workspace.output_part.write_bytes(b"half")
    workspace.concat_list.write_text("stale", encoding="utf-8")

    ws_module.prepare_workspace(workspace)

    assert workspace.index_dir.is_dir() and finished.exists()
    assert not any(path.exists() for path in (partial, workspace.output_part, workspace.concat_list))


def test_unlink_quiet_ignores_filesystem_errors(tmp_path):
    """Deleting a locked or missing file never raises."""
    _unlink_quiet(tmp_path / "missing.bin")
    with patch.object(Path, "unlink", side_effect=OSError("locked")):
        _unlink_quiet(tmp_path / "locked.bin")


def test_remove_workspace_deletes_root(tmp_path):
    """Removing the workspace leaves only the source behind."""
    workspace = _make_workspace(tmp_path)
    ws_module.prepare_workspace(workspace)
    ws_module.segment_path(workspace, 0, ".mov").write_bytes(b"x")

    ws_module.remove_workspace(workspace)

    assert not workspace.root.exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["tape.mpg"]


def test_compute_fingerprint_tracks_source_and_settings(tmp_path):
    """The fingerprint changes when the source or the settings change."""
    workspace = _make_workspace(tmp_path)
    source = workspace.root.parent / "tape.mpg"
    base = ws_module.compute_fingerprint(source, {"encoder": "prores"})

    assert base == ws_module.compute_fingerprint(source, {"encoder": "prores"})
    assert base != ws_module.compute_fingerprint(source, {"encoder": "av1"})
    source.write_bytes(b"source-changed")
    assert base != ws_module.compute_fingerprint(source, {"encoder": "prores"})


def test_compute_fingerprint_detects_same_second_same_size_edit(tmp_path):
    """A same-size edit inside one second still changes the fingerprint."""
    workspace = _make_workspace(tmp_path)
    source = workspace.root.parent / "tape.mpg"

    source.write_bytes(b"aaaaaa")
    os.utime(source, ns=(1_000_000_000, 1_000_000_000))
    before = ws_module.compute_fingerprint(source, {"encoder": "prores"})

    # Same byte count, same whole second, different content and nanoseconds.
    source.write_bytes(b"bbbbbb")
    os.utime(source, ns=(1_000_000_000, 1_400_000_000))
    after = ws_module.compute_fingerprint(source, {"encoder": "prores"})

    assert source.stat().st_size == 6
    assert before != after


def test_source_identity_detects_replaced_content_with_same_size_and_mtime(tmp_path):
    """Different bytes behind an identical path, size and mtime_ns still change the identity."""
    workspace = _make_workspace(tmp_path)
    source = workspace.root.parent / "tape.mpg"
    source.write_bytes(b"a" * 4096)
    os.utime(source, ns=(1_000_000_000, 1_000_000_000))
    before = ws_module.compute_source_identity(source)

    # A replacement copied in with preserved timestamps: same size, same mtime_ns.
    source.write_bytes(b"b" * 4096)
    os.utime(source, ns=(1_000_000_000, 1_000_000_000))
    after = ws_module.compute_source_identity(source)

    assert (source.stat().st_size, source.stat().st_mtime_ns) == (4096, 1_000_000_000)
    assert before != after


def test_sync_source_identity_drops_segments_for_replaced_content_with_same_size_and_mtime(tmp_path):
    """A same-size, same-mtime replacement must not reuse the previous segments or index."""
    workspace = _prepared_with_index_and_segment(tmp_path)
    source = workspace.root.parent / "tape.mpg"
    os.utime(source, ns=(1_000_000_000, 1_000_000_000))
    previous = ws_module.compute_source_identity(source)
    ws_module.save_state(workspace, {"version": ws_module.STATE_VERSION, "source_id": previous})

    source.write_bytes(bytes(reversed(source.read_bytes())))
    os.utime(source, ns=(1_000_000_000, 1_000_000_000))

    assert ws_module.sync_source_identity(workspace, ws_module.compute_source_identity(source)) is False
    assert (workspace.index_dir / "source.ffindex").exists() is False
    assert ws_module.segment_path(workspace, 0, ".mov").exists() is False


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        (0, [0]),
        (10, [0]),
        (ws_module.SAMPLE_CHUNK_BYTES * 3, [0, ws_module.SAMPLE_CHUNK_BYTES, ws_module.SAMPLE_CHUNK_BYTES * 2]),
        (
            ws_module.SAMPLE_CHUNK_BYTES * ws_module.SAMPLE_CHUNKS,
            list(range(0, ws_module.SAMPLE_CHUNK_BYTES * ws_module.SAMPLE_CHUNKS, ws_module.SAMPLE_CHUNK_BYTES)),
        ),
    ],
)
def test_sample_offsets_cover_small_files_completely(size, expected):
    """Files up to SAMPLE_CHUNKS chunks long are hashed in full."""
    assert getattr(ws_module, "_sample_offsets")(size) == expected


def test_sample_offsets_span_large_files_end_to_end():
    """Large files get SAMPLE_CHUNKS evenly spaced chunks, the last one ending at EOF."""
    size = 20 * 1024**3 + 12345  # a 20 GB tape
    offsets = getattr(ws_module, "_sample_offsets")(size)
    gaps = {b - a for a, b in zip(offsets, offsets[1:])}
    assert (len(offsets), offsets[0], offsets[-1] + ws_module.SAMPLE_CHUNK_BYTES) == (ws_module.SAMPLE_CHUNKS, 0, size)
    assert max(gaps) - min(gaps) <= 1


def test_sample_digest_reads_only_the_sampled_chunks(tmp_path, monkeypatch):
    """A large file is not read in full: only SAMPLE_CHUNKS chunks of SAMPLE_CHUNK_BYTES."""
    monkeypatch.setattr(ws_module, "SAMPLE_CHUNK_BYTES", 4)
    monkeypatch.setattr(ws_module, "SAMPLE_CHUNKS", 4)
    source = tmp_path / "tape.mpg"
    source.write_bytes(b"0123456789abcdefghijklmnopqrstuvwxyz")  # 36 bytes > 4 chunks of 4

    digest = getattr(ws_module, "_sample_digest")(source, source.stat().st_size)

    # step = (36 - 4) / 3 -> chunks at 0, 11, 21, 32
    expected = hashlib.sha256(b"0123" + b"bcde" + b"lmno" + b"wxyz").hexdigest()
    assert digest == expected


def test_state_round_trip_and_corrupt_state(tmp_path):
    """State is written atomically and unreadable state reads as empty."""
    workspace = _make_workspace(tmp_path)
    ws_module.prepare_workspace(workspace)

    assert ws_module.load_state(workspace) == {}
    ws_module.save_state(workspace, {"version": 1, "fingerprint": "abc"})
    assert json.loads(workspace.state_file.read_text(encoding="utf-8")) == {"version": 1, "fingerprint": "abc"}
    assert not workspace.state_file.with_suffix(".json.part").exists()


@pytest.mark.parametrize("corrupt", ["[1, 2", "[1, 2]", ""])
def test_load_state_treats_unreadable_state_as_empty(tmp_path, corrupt):
    """Truncated, non-object, or empty state files never break a resume."""
    workspace = _make_workspace(tmp_path)
    ws_module.prepare_workspace(workspace)
    workspace.state_file.write_text(corrupt, encoding="utf-8")
    assert ws_module.load_state(workspace) == {}


def _workspace_with_segment(tmp_path):
    """Prepared workspace holding one finished segment."""
    workspace = _make_workspace(tmp_path)
    ws_module.prepare_workspace(workspace)
    segment = ws_module.segment_path(workspace, 0, ".mov")
    segment.write_bytes(b"seg")
    return workspace, segment


def test_sync_state_without_state_clears_segments_and_records_fingerprint(tmp_path):
    """Segments from an unknown run are discarded and the fingerprint is saved."""
    workspace, segment = _workspace_with_segment(tmp_path)

    assert ws_module.sync_state(workspace, "fp-1") is False
    assert not segment.exists()
    assert ws_module.load_state(workspace) == {"version": ws_module.STATE_VERSION, "fingerprint": "fp-1"}


def test_sync_state_keeps_segments_when_fingerprint_matches(tmp_path):
    """Segments survive when the saved fingerprint equals the current one."""
    workspace, segment = _workspace_with_segment(tmp_path)
    ws_module.save_state(workspace, {"version": ws_module.STATE_VERSION, "fingerprint": "fp-1"})

    assert ws_module.sync_state(workspace, "fp-1") is True
    assert segment.exists()


def test_sync_state_clears_segments_when_fingerprint_changes(tmp_path):
    """A different fingerprint wipes the segments folder but keeps it usable."""
    workspace, segment = _workspace_with_segment(tmp_path)
    ws_module.save_state(workspace, {"version": ws_module.STATE_VERSION, "fingerprint": "fp-1"})

    assert ws_module.sync_state(workspace, "fp-2") is False
    assert not segment.exists()
    assert workspace.segments_dir.is_dir()


def test_plan_segments_covers_every_frame_exactly_once():
    """Segments are contiguous, inclusive, and cover the whole clip."""
    assert ws_module.plan_segments(10, 4) == [(0, 3), (4, 7), (8, 9)]
    assert ws_module.plan_segments(8, 4) == [(0, 3), (4, 7)]


def test_plan_segments_falls_back_to_single_open_segment():
    """Unknown frame counts, disabled or oversized segments give one open-ended segment."""
    assert ws_module.plan_segments(None, 100) == [(0, None)]
    assert ws_module.plan_segments(0, 100) == [(0, None)]
    assert ws_module.plan_segments(50, 0) == [(0, None)]
    assert ws_module.plan_segments(50, 50) == [(0, None)]


def test_segment_paths_are_zero_padded_and_distinct(tmp_path):
    """Finished and in-progress segment names never collide."""
    workspace = _make_workspace(tmp_path)
    assert ws_module.segment_path(workspace, 7, ".mkv").name == "seg_0007.mkv"
    assert ws_module.segment_part_path(workspace, 7, ".mkv").name == "seg_0007.part.mkv"
    assert ws_module.segment_part_path(workspace, 7, ".mkv").match("*.part.*")


def test_write_concat_list_escapes_quotes_and_uses_forward_slashes(tmp_path):
    """The concat list is valid ffconcat syntax even for awkward paths."""
    workspace = _make_workspace(tmp_path)
    ws_module.prepare_workspace(workspace)
    quoted = workspace.segments_dir / "it's seg.mov"
    plain = ws_module.segment_path(workspace, 1, ".mov")

    ws_module.write_concat_list(workspace, [quoted, plain])

    lines = workspace.concat_list.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "ffconcat version 1.0"
    assert lines[1] == f"file '{str(quoted.resolve()).replace(chr(92), '/').replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'"
    assert lines[2] == f"file '{str(plain.resolve()).replace(chr(92), '/')}'"
    assert "\\" not in lines[2]


def test_clear_segments_propagates_removal_failures(tmp_path):
    """A segment that cannot be deleted must fail the job, not be reused under a new fingerprint."""
    workspace = _make_workspace(tmp_path)
    ws_module.prepare_workspace(workspace)
    ws_module.segment_path(workspace, 0, ".mov").write_bytes(b"seg")

    with patch("modules.runtime.workspace.shutil.rmtree", side_effect=PermissionError("locked")):
        with pytest.raises(PermissionError):
            ws_module.clear_segments(workspace)


def test_sync_state_does_not_record_fingerprint_when_cleanup_fails(tmp_path):
    """The new fingerprint is only saved once the old segments are really gone."""
    workspace = _make_workspace(tmp_path)
    ws_module.prepare_workspace(workspace)
    ws_module.save_state(workspace, {"version": ws_module.STATE_VERSION, "fingerprint": "old"})

    with patch("modules.runtime.workspace.shutil.rmtree", side_effect=PermissionError("locked")):
        with pytest.raises(PermissionError):
            ws_module.sync_state(workspace, "new")

    assert ws_module.load_state(workspace)["fingerprint"] == "old"


def test_clear_folder_tolerates_missing_folder(tmp_path):
    """Clearing a folder that does not exist yet simply creates it."""
    workspace = _make_workspace(tmp_path)
    assert not workspace.index_dir.exists()

    ws_module.clear_index(workspace)

    assert workspace.index_dir.is_dir()


def _prepared_with_index_and_segment(tmp_path):
    """Workspace holding one index file and one finished segment."""
    workspace = _make_workspace(tmp_path)
    ws_module.prepare_workspace(workspace)
    (workspace.index_dir / "source.ffindex").write_bytes(b"index")
    ws_module.segment_path(workspace, 0, ".mov").write_bytes(b"seg")
    return workspace


def test_sync_source_identity_keeps_index_for_unchanged_source(tmp_path):
    """The same source keeps its index and segments across runs."""
    workspace = _prepared_with_index_and_segment(tmp_path)
    source = workspace.root.parent / "tape.mpg"
    identity = ws_module.compute_source_identity(source)
    ws_module.save_state(workspace, {"version": ws_module.STATE_VERSION, "source_id": identity})

    assert ws_module.sync_source_identity(workspace, identity) is True
    assert (workspace.index_dir / "source.ffindex").exists()
    assert ws_module.segment_path(workspace, 0, ".mov").exists()


def test_sync_source_identity_drops_index_and_segments_for_replaced_source(tmp_path):
    """A replaced source file invalidates the index as well as the segments."""
    workspace = _prepared_with_index_and_segment(tmp_path)
    ws_module.save_state(workspace, {"version": ws_module.STATE_VERSION, "source_id": "previous-file"})

    index_file = workspace.index_dir / "source.ffindex"
    segment = ws_module.segment_path(workspace, 0, ".mov")

    assert ws_module.sync_source_identity(workspace, "current-file") is False
    assert (index_file.exists(), segment.exists()) == (False, False)
    assert (workspace.index_dir.is_dir(), workspace.segments_dir.is_dir()) == (True, True)
    assert ws_module.load_state(workspace)["source_id"] == "current-file"


def test_sync_state_preserves_recorded_source_identity(tmp_path):
    """Replacing the settings fingerprint must not forget which source it belongs to."""
    workspace = _make_workspace(tmp_path)
    ws_module.prepare_workspace(workspace)
    ws_module.sync_source_identity(workspace, "src-1")

    ws_module.sync_state(workspace, "fp-1")

    state = ws_module.load_state(workspace)
    assert state["source_id"] == "src-1" and state["fingerprint"] == "fp-1"


def test_compute_source_identity_ignores_settings(tmp_path):
    """Source identity depends only on the file, never on processing settings."""
    workspace = _make_workspace(tmp_path)
    source = workspace.root.parent / "tape.mpg"

    assert ws_module.compute_source_identity(source) == ws_module.compute_source_identity(source)
    assert ws_module.compute_source_identity(source) != ws_module.compute_fingerprint(source, {"encoder": "prores"})


@pytest.mark.parametrize(
    ("first_bytes", "first_frames", "total_frames", "expected"),
    [
        (1_000, 100, 720_000, 7_200_000),
        (1_000, 0, 720_000, None),
        (1_000, 100, None, None),
        (1_000, 100, 0, None),
    ],
)
def test_project_output_bytes_extrapolates_from_the_first_segment(first_bytes, first_frames, total_frames, expected):
    """The projection scales the first segment's size to the whole clip, or gives up."""
    assert ws_module.project_output_bytes(first_bytes, first_frames, total_frames) == expected


def test_mux_space_needed_adds_margin_and_ignores_missing_segments(tmp_path):
    """The join needs the segments' bytes again plus a margin; absent files add nothing."""
    workspace = _make_workspace(tmp_path)
    ws_module.prepare_workspace(workspace)
    seg0 = ws_module.segment_path(workspace, 0, ".mov")
    seg1 = ws_module.segment_path(workspace, 1, ".mov")
    seg0.write_bytes(b"a" * 1000)
    seg1.write_bytes(b"b" * 3000)
    missing = ws_module.segment_path(workspace, 2, ".mov")

    needed = ws_module.mux_space_needed([seg0, seg1, missing])

    assert needed == int(4000 * ws_module.MUX_SPACE_MARGIN) + ws_module.MUX_SPACE_MARGIN_BYTES


def test_free_space_bytes_reads_the_workspace_drive(tmp_path):
    """Free space is measured on the drive that holds the workspace."""
    workspace = _make_workspace(tmp_path)
    ws_module.prepare_workspace(workspace)
    with patch("modules.runtime.workspace.shutil.disk_usage", return_value=SimpleNamespace(total=100, used=40, free=60)) as usage:
        assert ws_module.free_space_bytes(workspace) == 60
    usage.assert_called_once_with(workspace.root)


@pytest.mark.parametrize(
    ("total_frames", "segment_frames", "expected"),
    [
        (None, 15_000, "the frame count could not be probed"),
        (0, 15_000, "the frame count could not be probed"),
        (720_000, 0, "resume_segment_minutes is 0"),
        (720_000, 15_000, None),
        (100, 15_000, None),
    ],
)
def test_single_segment_reason_names_only_the_cases_that_lose_resume(total_frames, segment_frames, expected):
    """Unknown frame counts and disabled segmentation are reported; a short clip is not."""
    assert ws_module.single_segment_reason(total_frames, segment_frames) == expected


def test_plan_segments_handles_a_four_hour_tape():
    """A 4 h PAL tape at 50 fps output splits into 48 five-minute segments that tile it exactly."""
    total = 4 * 3600 * 50
    plan = ws_module.plan_segments(total, 5 * 60 * 50)

    assert len(plan) == 48
    assert plan[0] == (0, 14_999)
    assert plan[-1] == (705_000, 719_999)
    assert all(plan[i][1] + 1 == plan[i + 1][0] for i in range(len(plan) - 1))
