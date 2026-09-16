"""Resume and temp-hygiene tests for the segmented processing pipeline.

These run ``process_video`` against real files in a temp folder, mocking only
the external boundaries (vspipe/FFmpeg processes and ffprobe durations), so
the workspace layout, resume logic, and cleanup are exercised for real.
"""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from modules.runtime import pipeline
from modules.runtime import workspace as ws_module

SEGMENT_FRAMES = 60

# The pipeline's stage helpers are module-private; bind them once here, the way
# the rest of the suite binds private seams, instead of reaching through the
# module attribute at every call site.
_get_output_path = getattr(pipeline, "_get_output_path")
_promote_segment = getattr(pipeline, "_promote_segment")
_finalize_encoding_success = getattr(pipeline, "_finalize_encoding_success")
_update_encoding_progress = getattr(pipeline, "_update_encoding_progress")
_run_encoding_pipeline = getattr(pipeline, "_run_encoding_pipeline")


def _fake_get_vpy_info(_vspipe_exe, _script, *_args):
    """Report a 200-frame, 30 fps clip so the plan yields four segments."""
    return 200, 30.0, 720, 576, "YUV420P16"


def _fake_get_duration(file_path, _stream_type="v"):
    """Any file that exists with content has a positive duration."""
    path = Path(file_path)
    return 5.0 if path.exists() and path.stat().st_size > 0 else 0.0


class FakeEncoder:
    """Simulate the vspipe->FFmpeg segment run by writing the target file."""

    def __init__(self, fail_at: int | None = None):
        self.fail_at = fail_at
        self.calls: list[list[str]] = []

    def __call__(self, vspipe_cmd, ffmpeg_cmd, _duration_sec, _offset_sec=0.0):
        self.calls.append(list(vspipe_cmd))
        if self.fail_at is not None and len(self.calls) == self.fail_at:
            return False
        Path(ffmpeg_cmd[-1]).write_bytes(b"segment-data")
        return True


def _fake_mux(cmd, check=False, capture_output=False):
    """Simulate the concat+mux FFmpeg call by writing the output part file."""
    assert check is False and capture_output is True
    Path(cmd[-1]).write_bytes(b"muxed")
    return subprocess.CompletedProcess(cmd, 0, b"", b"")


@pytest.fixture(name="source")
def _source(tmp_path):
    """Create a fake source video inside an isolated folder."""
    source = tmp_path / "tape.mpg"
    source.write_bytes(b"source")
    return source


def _fake_create_vpy_script(_input_file, output_script, *_args, **_kwargs):
    """Write a placeholder script where the real generator would."""
    Path(output_script).write_text("clip", encoding="utf-8")


def _run(source: Path, encoder: FakeEncoder, mux=_fake_mux):
    """Run process_video with the external boundaries replaced."""
    with (
        patch("modules.runtime.pipeline.create_vpy_script", side_effect=_fake_create_vpy_script),
        patch("modules.runtime.pipeline.get_vpy_info", side_effect=_fake_get_vpy_info),
        patch("modules.runtime.pipeline.get_duration", side_effect=_fake_get_duration),
        patch("modules.runtime.pipeline.resolve_vspipe_executable", return_value="vspipe"),
        patch("modules.runtime.pipeline._run_encoding_pipeline", side_effect=encoder),
        patch("modules.runtime.pipeline.subprocess.run", side_effect=mux),
        patch("modules.runtime.encoders.get_available_ffmpeg_encoders", return_value=frozenset({"libsvtav1"})),
        patch("modules.runtime.pipeline.RESUME_SEGMENT_MINUTES", SEGMENT_FRAMES / 60 / 30.0),
        patch("modules.runtime.pipeline.CONFIG", {"auto_drift_correction": False}),
        patch("modules.runtime.pipeline.update_progress"),
        patch("modules.runtime.pipeline.log_info"),
        patch("modules.runtime.pipeline.log_debug"),
    ):
        return pipeline.process_video(source)


def _workspace_for(source: Path) -> ws_module.VideoWorkspace:
    return ws_module.build_workspace(source, _get_output_path(source))


def test_success_leaves_only_source_and_output(source):
    """A clean run writes the final output and removes every temp file."""
    encoder = FakeEncoder()
    result = _run(source, encoder)

    assert result["status"] == "success"
    output = _get_output_path(source)
    assert output.read_bytes() == b"muxed"
    assert sorted(p.name for p in source.parent.iterdir()) == sorted([source.name, output.name])


def test_segments_cover_the_clip_in_order(source):
    """vspipe is invoked once per planned segment with inclusive frame ranges."""
    encoder = FakeEncoder()
    _run(source, encoder)

    ranges = [call[3:7] for call in encoder.calls]
    assert ranges[0] == ["--start", "0", "--end", "59"]
    assert ranges[-1] == ["--start", "180", "--end", "199"]
    assert len(ranges) == 4


def test_all_temp_files_live_inside_workspace(source):
    """While encoding, every temp artifact sits inside ``<file name>.autovhs-tmp``."""
    workspace = _workspace_for(source)
    seen: dict[str, list[str]] = {}

    def spy_encoder(vspipe_cmd, ffmpeg_cmd, _duration_sec, _offset_sec=0.0):
        Path(ffmpeg_cmd[-1]).write_bytes(b"segment-data")
        expected = {source.name, workspace.root.name}
        seen.setdefault("outside", []).extend(p.name for p in source.parent.iterdir() if p.name not in expected)
        seen.setdefault("script", []).append(vspipe_cmd[-2])
        return True

    result = _run(source, spy_encoder)

    assert result["status"] == "success"
    assert seen["outside"] == []
    assert all(Path(script) == workspace.script for script in seen["script"])
    assert not workspace.root.exists()


def _finished_segments(workspace: ws_module.VideoWorkspace) -> list[str]:
    """Names of completed segment files currently in the workspace."""
    return sorted(p.name for p in workspace.segments_dir.glob("seg_*.mov"))


def test_interrupted_run_keeps_finished_segments(source):
    """A failure mid-way keeps the workspace with exactly the finished segments."""
    workspace = _workspace_for(source)
    result = _run(source, FakeEncoder(fail_at=3))

    assert result["status"] == "failed"
    assert _finished_segments(workspace) == ["seg_0000.mov", "seg_0001.mov"]
    assert not _get_output_path(source).exists()


def test_rerun_resumes_from_last_finished_segment(source):
    """The rerun skips finished segments, encodes the rest, and cleans up."""
    workspace = _workspace_for(source)
    _run(source, FakeEncoder(fail_at=3))

    second = FakeEncoder()
    result = _run(source, second)

    assert result["status"] == "success"
    assert [call[3:7] for call in second.calls] == [["--start", "120", "--end", "179"], ["--start", "180", "--end", "199"]]
    assert not workspace.root.exists()


def test_stale_partial_segment_is_discarded_on_restart(source):
    """A half-written ``.part`` segment from a power cut is never trusted."""
    workspace = _workspace_for(source)
    ws_module.prepare_workspace(workspace)
    stale = ws_module.segment_part_path(workspace, 0, ".mov")
    stale.write_bytes(b"half")

    result = _run(source, FakeEncoder())

    assert result["status"] == "success"
    assert not stale.exists()
    assert not workspace.root.exists()


def test_changed_settings_invalidate_old_segments(source):
    """Segments made with different settings are thrown away, not reused."""
    workspace = _workspace_for(source)
    _run(source, FakeEncoder(fail_at=2))
    assert ws_module.segment_path(workspace, 0, ".mov").exists()

    with patch("modules.runtime.pipeline.ENCODER", "av1"):
        second = FakeEncoder()
        result = _run(source, second)

    assert result["status"] == "success"
    assert len(second.calls) == 4
    assert not workspace.root.exists()


def test_mux_failure_keeps_workspace_and_reports_stderr(source):
    """A failed mux keeps segments for resume and logs FFmpeg's error tail."""
    workspace = _workspace_for(source)

    def failing_mux(cmd, **_kwargs):
        return subprocess.CompletedProcess(cmd, 1, b"", b"line1\nconcat failed\n")

    with patch("modules.runtime.pipeline.log_error") as mock_error:
        result = _run(source, FakeEncoder(), mux=failing_mux)

    assert result["status"] == "failed" and not _get_output_path(source).exists()
    assert all(ws_module.segment_path(workspace, i, ".mov").exists() for i in range(4))
    assert any("concat failed" in call.args[0] for call in mock_error.call_args_list)


def test_mux_launch_error_is_reported(source):
    """An OS error while launching FFmpeg is logged, not raised."""

    def broken_mux(*_args, **_kwargs):
        raise OSError("ffmpeg missing")

    with patch("modules.runtime.pipeline.log_error") as mock_error:
        result = _run(source, FakeEncoder(), mux=broken_mux)

    assert result["status"] == "failed"
    assert any("ffmpeg missing" in call.args[0] for call in mock_error.call_args_list)


def test_existing_valid_output_skips_and_removes_workspace(source):
    """A valid output means skip, and any leftover workspace is removed."""
    workspace = _workspace_for(source)
    ws_module.prepare_workspace(workspace)
    _get_output_path(source).write_bytes(b"final")

    result = _run(source, FakeEncoder())

    assert result["status"] == "skipped"
    assert not workspace.root.exists()


def test_segment_promote_failure_is_logged(tmp_path):
    """A rename failure after a segment finishes is reported as a failed segment."""
    with patch("modules.runtime.pipeline.log_error") as mock_error:
        assert _promote_segment(tmp_path / "missing.part.mov", tmp_path / "seg.mov") is False
    assert mock_error.called


def test_segment_without_frame_count_uses_open_range(source):
    """Unknown frame counts encode the whole clip in one open-ended segment."""
    encoder = FakeEncoder()
    with patch("modules.runtime.pipeline.get_vpy_info", return_value=(None, None, None, None, None)):
        with (
            patch("modules.runtime.pipeline.create_vpy_script", side_effect=_fake_create_vpy_script),
            patch("modules.runtime.pipeline.get_duration", side_effect=_fake_get_duration),
            patch("modules.runtime.pipeline.resolve_vspipe_executable", return_value="vspipe"),
            patch("modules.runtime.pipeline._run_encoding_pipeline", side_effect=encoder),
            patch("modules.runtime.pipeline.subprocess.run", side_effect=_fake_mux),
            patch("modules.runtime.pipeline.CONFIG", {"auto_drift_correction": False}),
            patch("modules.runtime.pipeline.update_progress"),
            patch("modules.runtime.pipeline.log_info"),
            patch("modules.runtime.pipeline.log_debug"),
        ):
            result = pipeline.process_video(source)

    assert result["status"] == "success"
    assert len(encoder.calls) == 1
    assert "--start" not in encoder.calls[0]


def test_finalize_reports_undeletable_workspace(tmp_path):
    """If the workspace cannot be removed the operator is told, not left guessing."""
    workspace = ws_module.build_workspace(tmp_path / "a.mp4", tmp_path / "a_out.mov")
    ws_module.prepare_workspace(workspace)
    with patch("modules.runtime.pipeline.remove_workspace"):
        with patch("modules.runtime.pipeline.update_progress"):
            with patch("modules.runtime.pipeline.log_error") as mock_error:
                _finalize_encoding_success(workspace, "00:00:05,000")
    assert any("Could not remove workspace" in call.args[0] for call in mock_error.call_args_list)


def test_progress_is_offset_by_segment_start():
    """Progress for a later segment starts at that segment's position, capped at 100."""
    with patch("modules.runtime.pipeline.update_progress") as mock_progress:
        _update_encoding_progress("frame=10 time=00:00:10.00 speed=2.0x", 100.0, "00:01:40,000", offset_sec=50.0)
        _update_encoding_progress("frame=10 time=00:01:00.00 speed=2.0x", 100.0, "00:01:40,000", offset_sec=50.0)

    first_pct, second_pct = (call.args[0] for call in mock_progress.call_args_list)
    assert first_pct == pytest.approx(60.0)
    assert second_pct == pytest.approx(100.0)
    assert mock_progress.call_args_list[0].args[2] == "00:01:00,000 / 00:01:40,000"


def test_run_encoding_pipeline_forwards_offset():
    """The offset reaches the stderr reader so progress is segment-aware."""
    with patch("subprocess.Popen") as mock_popen:
        proc = MagicMock()
        proc.__enter__.return_value = proc
        proc.__exit__.return_value = False
        proc.returncode = 0
        proc.stdout = MagicMock()
        proc.stderr = None
        mock_popen.return_value = proc
        with patch("modules.runtime.pipeline.get_vspipe_env", return_value={}):
            with patch("threading.Thread"):
                with patch("modules.runtime.pipeline._read_ffmpeg_stderr", return_value=[]) as mock_read:
                    assert _run_encoding_pipeline(["vspipe"], ["ffmpeg"], 100.0, 25.0) is True

    assert mock_read.call_args.args[3] == 25.0


_build_fingerprint_settings = getattr(pipeline, "_build_fingerprint_settings")


def _fingerprint_with(hw_settings: dict, encoder: str = "av1") -> dict:
    """Resolve the fingerprint settings under one hardware/encoder combination."""
    with patch.multiple("modules.runtime.pipeline", ENCODER=encoder, HW_SETTINGS=hw_settings):
        with patch("modules.runtime.encoders.get_available_ffmpeg_encoders", return_value=frozenset({"libsvtav1"})):
            return _build_fingerprint_settings(SEGMENT_FRAMES)


def test_fingerprint_changes_when_the_resolved_video_encoder_changes():
    """NVENC and CPU AV1 segments must never be concatenated together."""
    nvenc = _fingerprint_with({"cpu_threads": 8, "has_av1_nvenc": True})
    cpu = _fingerprint_with({"cpu_threads": 8, "has_av1_nvenc": False})

    assert "av1_nvenc" in nvenc["video_encoder_args"]
    assert "libsvtav1" in cpu["video_encoder_args"]
    assert nvenc != cpu


def test_fingerprint_changes_when_opencl_settings_change():
    """QTGMC OpenCL settings alter the decoded frames, so they must invalidate segments."""
    base = {"cpu_threads": 8, "has_av1_nvenc": False, "use_gpu_opencl": True, "gpu_device_index": 0}
    other_device = dict(base, gpu_device_index=1)
    cpu_only = dict(base, use_gpu_opencl=False)

    assert _fingerprint_with(base) != _fingerprint_with(other_device)
    assert _fingerprint_with(base) != _fingerprint_with(cpu_only)
    assert _fingerprint_with(base)["use_gpu_opencl"] is True
    assert _fingerprint_with(cpu_only)["gpu_device_index"] == 0


def test_fingerprint_is_json_serialisable_for_hashing(source):
    """compute_fingerprint must accept the settings mapping unchanged."""
    settings = _fingerprint_with({"cpu_threads": 8, "has_av1_nvenc": True})
    assert ws_module.compute_fingerprint(source, settings) != ws_module.compute_fingerprint(source, {})


def test_replaced_source_discards_index_before_the_probe(source):
    """A changed source clears the workspace index before any script is probed."""
    workspace = _workspace_for(source)
    _run(source, FakeEncoder(fail_at=2))
    stale_index = workspace.index_dir / "source.ffindex"
    stale_index.write_bytes(b"built-from-old-file")
    order: list[str] = []

    def probe(_vspipe_exe, _script, *_args):
        order.append("index-present" if stale_index.exists() else "index-cleared")
        return _fake_get_vpy_info(_vspipe_exe, _script)

    # Same size, different content and mtime: the identity must still change.
    source.write_bytes(b"SOURCE")
    with patch("modules.runtime.pipeline.get_vpy_info", side_effect=probe):
        with (
            patch("modules.runtime.pipeline.create_vpy_script", side_effect=_fake_create_vpy_script),
            patch("modules.runtime.pipeline.get_duration", side_effect=_fake_get_duration),
            patch("modules.runtime.pipeline.resolve_vspipe_executable", return_value="vspipe"),
            patch("modules.runtime.pipeline._run_encoding_pipeline", side_effect=FakeEncoder()),
            patch("modules.runtime.pipeline.subprocess.run", side_effect=_fake_mux),
            patch("modules.runtime.encoders.get_available_ffmpeg_encoders", return_value=frozenset({"libsvtav1"})),
            patch("modules.runtime.pipeline.RESUME_SEGMENT_MINUTES", SEGMENT_FRAMES / 60 / 30.0),
            patch("modules.runtime.pipeline.CONFIG", {"auto_drift_correction": False}),
            patch("modules.runtime.pipeline.update_progress"),
            patch("modules.runtime.pipeline.log_info"),
            patch("modules.runtime.pipeline.log_debug"),
        ):
            result = pipeline.process_video(source)

    assert result["status"] == "success"
    assert order == ["index-cleared"]


def test_unchanged_source_keeps_index_across_runs(source):
    """The same source reuses its index on the rerun."""
    workspace = _workspace_for(source)
    _run(source, FakeEncoder(fail_at=2))
    index_file = workspace.index_dir / "source.ffindex"
    index_file.write_bytes(b"index")
    seen: list[bool] = []

    def probe(_vspipe_exe, _script, *_args):
        seen.append(index_file.exists())
        return _fake_get_vpy_info(_vspipe_exe, _script)

    with patch("modules.runtime.pipeline.get_vpy_info", side_effect=probe):
        with (
            patch("modules.runtime.pipeline.create_vpy_script", side_effect=_fake_create_vpy_script),
            patch("modules.runtime.pipeline.get_duration", side_effect=_fake_get_duration),
            patch("modules.runtime.pipeline.resolve_vspipe_executable", return_value="vspipe"),
            patch("modules.runtime.pipeline._run_encoding_pipeline", side_effect=FakeEncoder()),
            patch("modules.runtime.pipeline.subprocess.run", side_effect=_fake_mux),
            patch("modules.runtime.encoders.get_available_ffmpeg_encoders", return_value=frozenset({"libsvtav1"})),
            patch("modules.runtime.pipeline.RESUME_SEGMENT_MINUTES", SEGMENT_FRAMES / 60 / 30.0),
            patch("modules.runtime.pipeline.CONFIG", {"auto_drift_correction": False}),
            patch("modules.runtime.pipeline.update_progress"),
            patch("modules.runtime.pipeline.log_info"),
            patch("modules.runtime.pipeline.log_debug"),
        ):
            pipeline.process_video(source)

    assert seen == [True]


_sync_source_identity_with_log = getattr(pipeline, "_sync_source_identity_with_log")
CHANGED_LINE = "Source file changed since the workspace was created"


def _source_change_messages(source: Path, workspace) -> list[str]:
    """Run the identity check and return any source-changed log lines it emitted."""
    with patch("modules.runtime.pipeline.log_info") as mock_log:
        _sync_source_identity_with_log(source, workspace)
    return [call.args[0] for call in mock_log.call_args_list if CHANGED_LINE in call.args[0]]


def test_fresh_workspace_does_not_report_a_changed_source(source):
    """A brand-new workspace is initialised silently."""
    workspace = _workspace_for(source)
    ws_module.prepare_workspace(workspace)

    assert _source_change_messages(source, workspace) == []
    assert ws_module.load_state(workspace)["source_id"] == ws_module.compute_source_identity(source)


def test_replaced_source_is_reported_once(source):
    """Only a workspace built from a different file logs the discard."""
    workspace = _workspace_for(source)
    ws_module.prepare_workspace(workspace)
    _source_change_messages(source, workspace)

    source.write_bytes(b"different-content")
    assert len(_source_change_messages(source, workspace)) == 1
    # Unchanged on the next run again.
    assert _source_change_messages(source, workspace) == []


_log_segment_plan = getattr(pipeline, "_log_segment_plan")
_ensure_mux_space = getattr(pipeline, "_ensure_mux_space")
_log_space_projection = getattr(pipeline, "_log_space_projection")


def _logged(mock_log) -> str:
    return "\n".join(call.args[0] for call in mock_log.call_args_list if call.args)


def test_probe_timeout_is_scaled_to_the_source_size(source):
    """A long tape gets a longer index-build timeout than the fixed default."""
    source.write_bytes(b"x" * 2_000)
    workspace = _workspace_for(source)
    ws_module.prepare_workspace(workspace)
    build_processing_commands = getattr(pipeline, "_build_processing_commands")
    with (
        patch("modules.runtime.pipeline.create_vpy_script", side_effect=_fake_create_vpy_script),
        patch("modules.runtime.pipeline.get_vpy_info", side_effect=_fake_get_vpy_info) as probe,
        patch("modules.runtime.pipeline.get_duration", side_effect=_fake_get_duration),
        patch("modules.runtime.pipeline.resolve_vspipe_executable", return_value="vspipe"),
        patch("modules.runtime.encoders.get_available_ffmpeg_encoders", return_value=frozenset({"libsvtav1"})),
        patch("modules.runtime.pipeline.CONFIG", {"auto_drift_correction": False}),
        patch("modules.runtime.pipeline.log_info"),
    ):
        build_processing_commands(source, workspace)

    assert probe.call_args.args[2] == pipeline.resolve_info_timeout(source.stat().st_size)
    assert probe.call_args.args[2] > 1800 - 1


def test_plan_log_warns_when_resume_is_impossible():
    """An unknown frame count or segmentation switched off is called out as an error."""
    with patch("modules.runtime.pipeline.log_error") as mock_error:
        _log_segment_plan([(0, None)], False, None, 15_000)
        _log_segment_plan([(0, None)], False, 720_000, 0)
    logged = _logged(mock_error)
    assert "frame count could not be probed" in logged
    assert "resume_segment_minutes is 0" in logged


def test_plan_log_is_quiet_for_a_normal_plan():
    """A normal multi-segment plan logs the plan, not a warning."""
    with patch("modules.runtime.pipeline.log_error") as mock_error:
        with patch("modules.runtime.pipeline.log_info") as mock_info:
            _log_segment_plan([(0, 14_999), (15_000, 29_999)], True, 30_000, 15_000)
    assert not mock_error.called
    assert "2 segment(s)" in _logged(mock_info)


def test_mux_refused_without_enough_space_keeps_segments(source):
    """The join never starts when it cannot finish, and the segments stay for resume."""
    workspace = _workspace_for(source)
    with patch("modules.runtime.pipeline.free_space_bytes", return_value=1):
        with patch("modules.runtime.pipeline.log_error") as mock_error:
            result = _run(source, FakeEncoder())

    assert result["status"] == "failed"
    assert "Not enough free space to join" in _logged(mock_error)
    assert _finished_segments(workspace) == ["seg_0000.mov", "seg_0001.mov", "seg_0002.mov", "seg_0003.mov"]
    assert not workspace.concat_list.exists()


def test_space_projection_logs_once_and_warns_when_short(source):
    """The first encoded segment yields one projection; a tight drive gets a warning."""
    workspace = _workspace_for(source)
    ws_module.prepare_workspace(workspace)
    seg = ws_module.segment_path(workspace, 0, ".mov")
    seg.write_bytes(b"x" * 1_000)
    job = {"total_frames": 720_000}

    with patch("modules.runtime.pipeline.free_space_bytes", return_value=5_000_000):
        with patch("modules.runtime.pipeline.log_info") as mock_info, patch("modules.runtime.pipeline.log_error") as mock_error:
            _log_space_projection(job, workspace, seg, 0, 99)
            _log_space_projection(job, workspace, seg, 100, 199)

    assert _logged(mock_info).count("[SPACE] Projected output") == 1
    assert "free space is below the projected peak" in _logged(mock_error)
    assert job["space_projected"] is True


def test_space_projection_skips_open_ended_segments(source):
    """With no frame span there is nothing to extrapolate from."""
    workspace = _workspace_for(source)
    with patch("modules.runtime.pipeline.log_info") as mock_info:
        _log_space_projection({"total_frames": 100}, workspace, workspace.root / "seg.mov", 0, None)
    assert "[SPACE]" not in _logged(mock_info)
