"""Unit tests for native vspipe helper behavior."""

import builtins
import importlib
import io
import sys
from importlib.machinery import ModuleSpec
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _cleanup_vspipe_native_module_cache():
    """Ensure vspipe_native is not cached across test boundaries."""
    sys.modules.pop("modules.runtime.vspipe_native", None)
    yield
    sys.modules.pop("modules.runtime.vspipe_native", None)


def _load_vspipe_native(fake_vs):
    """Reload vspipe_native with a fake vapoursynth module injected."""
    sys.modules.pop("modules.runtime.vspipe_native", None)
    with patch.dict(sys.modules, {"vapoursynth": fake_vs}):
        native = importlib.import_module("modules.runtime.vspipe_native")

        return importlib.reload(native)


def test_vspipe_native_main_usage_and_missing_script():
    """Handle usage errors and missing script paths in main entrypoint."""
    fake_vs = SimpleNamespace(get_outputs=lambda: {}, VideoOutputTuple=tuple, VideoNode=object)
    native = _load_vspipe_native(fake_vs)

    with patch.object(native.sys, "argv", ["vspipe_native"]):
        with patch.object(native.sys, "exit", side_effect=SystemExit(1)):
            with pytest.raises(SystemExit):
                native.main()

    with patch.object(native.sys, "argv", ["vspipe_native", "missing.vpy"]):
        with patch.object(native.os.path, "exists", return_value=False):
            with patch.object(native.sys, "exit", side_effect=SystemExit(1)):
                with pytest.raises(SystemExit):
                    native.main()


def test_vspipe_native_main_no_outputs_and_invalid_output_type():
    """Fail when no outputs are produced or clip type is invalid."""
    fake_vs = SimpleNamespace(get_outputs=lambda: {}, VideoOutputTuple=tuple, VideoNode=object)
    native = _load_vspipe_native(fake_vs)

    with patch.object(native.sys, "argv", ["vspipe_native", "ok.vpy"]):
        with patch.object(native.os.path, "exists", return_value=True):
            with patch.object(native.runpy, "run_path"):
                with patch.object(native.sys, "exit", side_effect=SystemExit(1)):
                    with pytest.raises(SystemExit):
                        native.main()

    fake_vs_bad = SimpleNamespace(get_outputs=lambda: {0: "not-a-clip"}, VideoOutputTuple=tuple, VideoNode=dict)
    native_bad = _load_vspipe_native(fake_vs_bad)
    with patch.object(native_bad.sys, "argv", ["vspipe_native", "ok.vpy"]):
        with patch.object(native_bad.os.path, "exists", return_value=True):
            with patch.object(native_bad.runpy, "run_path"):
                with patch.object(native_bad.sys, "exit", side_effect=SystemExit(1)):
                    with pytest.raises(SystemExit):
                        native_bad.main()


def test_vspipe_native_main_raw_and_y4m_paths():
    """Dispatch output writing to raw or y4m paths based on flags."""

    class FakeVideoNode:
        """Simple clip holder for output tuple simulation."""

        def __init__(self):
            self.width = 720
            self.height = 576
            self.num_frames = 1
            self.fps = SimpleNamespace(numerator=30000, denominator=1001)
            self.format = SimpleNamespace(id=0, name="YUV420P10", num_planes=1)

    class FakeVideoOutputTuple:
        """Tuple-like wrapper that exposes clip attribute."""

        def __init__(self, clip):
            self.clip = clip

    clip = FakeVideoNode()

    fake_vs = SimpleNamespace(
        get_outputs=lambda: {0: FakeVideoOutputTuple(clip)},
        VideoOutputTuple=FakeVideoOutputTuple,
        VideoNode=FakeVideoNode,
        YUV420P8=1,
        YUV420P10=0,
        YUV420P16=3,
        YUV422P10=4,
        YUV444P10=5,
    )
    native = _load_vspipe_native(fake_vs)

    with patch.object(native.sys, "argv", ["vspipe_native", "ok.vpy", "--raw"]):
        with patch.object(native.os.path, "exists", return_value=True):
            with patch.object(native.runpy, "run_path"):
                with patch.object(native, "_write_raw_output") as mock_raw:
                    native.main()
                    assert mock_raw.called

    with patch.object(native.sys, "argv", ["vspipe_native", "ok.vpy"]):
        with patch.object(native.os.path, "exists", return_value=True):
            with patch.object(native.runpy, "run_path"):
                with patch.object(native, "_write_y4m_output") as mock_y4m:
                    native.main()
                    assert mock_y4m.called


def test_vspipe_native_write_raw_success_and_error_path():
    """Write raw frames and handle error and broken-pipe branches."""
    fake_vs = SimpleNamespace(get_outputs=lambda: {}, VideoOutputTuple=tuple, VideoNode=object)
    native = _load_vspipe_native(fake_vs)

    class RawFrame:
        """Single-plane frame returning static bytes."""

        format = SimpleNamespace(num_planes=1)

        def __getitem__(self, _idx):
            """Return a static plane payload."""
            return b"abc"

    frame = RawFrame()

    class RawClip:
        """Clip with one frame for raw writer happy path."""

        num_frames = 1

        def frames(self, prefetch=1):
            """Yield one frame and assert requested prefetch."""
            assert prefetch == 1
            return [frame]

    clip = RawClip()

    fake_out = io.BytesIO()
    fake_stdout = SimpleNamespace(buffer=fake_out, close=lambda: None)
    with patch.object(native.sys, "stdout", fake_stdout):
        getattr(native, "_write_raw_output")(clip)
    assert fake_out.getvalue() == b"abc"

    class FailingClip:
        """Clip raising an I/O error when iterating frames."""

        num_frames = 1

        def frames(self, prefetch=1):
            """Raise an error after prefetch assertion."""
            assert prefetch == 1
            raise OSError("boom")

    failing_clip = FailingClip()
    with patch.object(native.sys, "stdout", fake_stdout):
        with patch.object(native.sys, "exit", side_effect=SystemExit(1)):
            with pytest.raises(SystemExit):
                getattr(native, "_write_raw_output")(failing_clip)

    class BrokenOut:
        """Output stream simulation raising broken-pipe writes."""

        def write(self, _data):
            """Raise broken pipe to exercise graceful termination path."""
            raise BrokenPipeError

        def flush(self):
            """No-op flush for stream compatibility."""
            return None

    broken_stdout = SimpleNamespace(buffer=BrokenOut(), close=lambda: (_ for _ in ()).throw(OSError("close")))
    with patch.object(native.sys, "stdout", broken_stdout):
        with patch.object(native.sys, "exit", side_effect=SystemExit(0)):
            with pytest.raises(SystemExit):
                getattr(native, "_write_raw_output")(clip)


def test_vspipe_native_write_y4m_success_and_broken_pipe_path():
    """Write y4m output and validate broken-pipe/error handling."""
    fake_vs = SimpleNamespace(get_outputs=lambda: {}, VideoOutputTuple=tuple, VideoNode=object)
    native = _load_vspipe_native(fake_vs)
    native.np = None

    class PlaneFrame:
        """Frame exposing one byte plane."""

        format = SimpleNamespace(num_planes=1)

        def __getitem__(self, _idx):
            """Return static y4m plane payload."""
            return b"xyz"

    class Y4MClip:
        """Clip with one frame for y4m writer happy path."""

        num_frames = 1

        def frames(self, prefetch=1):
            """Yield one frame and assert requested prefetch."""
            assert prefetch == 1
            return [PlaneFrame()]

    clip = Y4MClip()

    fake_stdout = MagicMock()
    fake_stdout.fileno.return_value = 1
    fake_msvcrt = MagicMock()
    with patch.object(native.sys, "stdout", fake_stdout):
        with patch.object(native, "msvcrt", fake_msvcrt):
            with patch.object(native.sys, "platform", "win32"):
                with patch.object(native.os, "write", side_effect=lambda _fd, data: len(data)) as mock_write:
                    getattr(native, "_write_y4m_output")(clip, "YUV4MPEG2 header\n")
                    assert mock_write.call_count >= 3
                    fake_msvcrt.setmode.assert_called_once_with(1, native.O_BINARY_MODE)

    with patch.object(native.sys, "stdout", fake_stdout):
        with patch.object(native.os, "write", side_effect=BrokenPipeError):
            with patch.object(native.sys, "exit", side_effect=SystemExit(0)):
                with pytest.raises(SystemExit):
                    getattr(native, "_write_y4m_output")(clip, "H\n")

    class BadClip:
        """Clip failing during frame iteration."""

        num_frames = 1

        def frames(self, prefetch=1):
            """Raise runtime error after prefetch assertion."""
            assert prefetch == 1
            raise RuntimeError("frame")

    bad_clip = BadClip()
    with patch.object(native.sys, "stdout", fake_stdout):
        with patch.object(native.sys, "exit", side_effect=SystemExit(1)):
            with pytest.raises(SystemExit):
                getattr(native, "_write_y4m_output")(bad_clip, "YUV4MPEG2 header\n")


def test_vspipe_native_log_frame_progress_uses_one_based_count():
    """Log frame progress with one-based completed-frame numbers and flush when requested."""
    fake_vs = SimpleNamespace(get_outputs=lambda: {}, VideoOutputTuple=tuple, VideoNode=object)
    native = _load_vspipe_native(fake_vs)

    flush = MagicMock()
    with patch.object(native.sys, "stderr") as mock_stderr:
        getattr(native, "_log_frame_progress")(99, 1000, flush_output=flush)

    mock_stderr.write.assert_called_once_with("Wrote frame 100/1000\n")
    flush.assert_called_once_with()

    with patch.object(native.sys, "stderr") as mock_stderr:
        getattr(native, "_log_frame_progress")(0, 1000)

    mock_stderr.write.assert_not_called()


def test_vspipe_native_write_all_handles_partial_writes():
    """Retry writes when os.write returns partial progress."""
    fake_vs = SimpleNamespace(get_outputs=lambda: {}, VideoOutputTuple=tuple, VideoNode=object)
    native = _load_vspipe_native(fake_vs)

    with patch.object(native.os, "write", side_effect=[2, 3]) as mock_write:
        getattr(native, "_write_all")(1, b"hello")

    assert mock_write.call_count == 2


def test_vspipe_native_prefetch_uses_core_thread_count():
    """Use VapourSynth core thread count for prefetch when available."""

    class FakeFrame:
        """Frame used by raw writer prefetch assertion test."""

        format = SimpleNamespace(num_planes=1)

        def __getitem__(self, _idx):
            """Return static plane payload."""
            return b"d"

    class FakeClip:
        """Clip that records requested prefetch value."""

        num_frames = 1

        def __init__(self):
            self.prefetch = None

        def frames(self, prefetch=1):
            """Capture prefetch and yield one frame."""
            self.prefetch = prefetch
            return [FakeFrame()]

    fake_vs = SimpleNamespace(get_outputs=lambda: {}, VideoOutputTuple=tuple, VideoNode=object, core=SimpleNamespace(num_threads=6))
    native = _load_vspipe_native(fake_vs)
    native.np = None

    clip = FakeClip()
    fake_stdout = SimpleNamespace(buffer=io.BytesIO(), close=lambda: None)
    with patch.object(native.sys, "stdout", fake_stdout):
        getattr(native, "_write_raw_output")(clip)

    assert clip.prefetch == 6


def test_vspipe_native_main_run_path_error():
    """Exit with error when script execution raises at run_path."""

    class FakeVideoNode:
        """Simple clip holder for error-path setup."""

        def __init__(self):
            self.width = 16
            self.height = 16
            self.num_frames = 1
            self.fps = SimpleNamespace(numerator=1, denominator=1)
            self.format = SimpleNamespace(id=1, name="YUV420P8", num_planes=1)

    class FakeVideoOutputTuple:
        """Tuple-like wrapper that exposes clip attribute."""

        def __init__(self, clip):
            self.clip = clip

    clip = FakeVideoNode()

    fake_vs = SimpleNamespace(
        get_outputs=lambda: {0: FakeVideoOutputTuple(clip)},
        VideoOutputTuple=FakeVideoOutputTuple,
        VideoNode=FakeVideoNode,
        YUV420P8=1,
        YUV420P10=2,
        YUV420P16=3,
        YUV422P10=4,
        YUV444P10=5,
    )
    native = _load_vspipe_native(fake_vs)

    with patch.object(native.sys, "argv", ["vspipe_native", "ok.vpy"]):
        with patch.object(native.os.path, "exists", return_value=True):
            with patch.object(native.runpy, "run_path", side_effect=RuntimeError("script failed")):
                with patch.object(native.sys, "exit", side_effect=SystemExit(1)):
                    with pytest.raises(SystemExit):
                        native.main()


def test_vspipe_native_write_all_raises_on_short_write():
    """Raise OSError when os.write reports no write progress."""
    fake_vs = SimpleNamespace(get_outputs=lambda: {}, VideoOutputTuple=tuple, VideoNode=object)
    native = _load_vspipe_native(fake_vs)

    with patch.object(native.os, "write", return_value=0):
        with pytest.raises(OSError):
            getattr(native, "_write_all")(1, b"abc")


def test_vspipe_native_write_y4m_numpy_path_and_broken_pipe_close_error():
    """Cover numpy conversion path and close-error branch after broken pipe."""
    fake_vs = SimpleNamespace(get_outputs=lambda: {}, VideoOutputTuple=tuple, VideoNode=object)
    native = _load_vspipe_native(fake_vs)

    class FakeNumpyArray:
        """Small numpy-like shim exposing tobytes."""

        def __init__(self, payload):
            self._payload = payload

        def tobytes(self):
            """Return byte payload for y4m writer."""
            return self._payload

    def _asarray_plane(plane):
        """Convert a plane to a numpy-like wrapper."""
        return FakeNumpyArray(plane)

    native.np = SimpleNamespace(asarray=_asarray_plane)
    native.msvcrt = None

    class PlaneFrame:
        """Frame exposing one byte plane."""

        format = SimpleNamespace(num_planes=1)

        def __getitem__(self, _idx):
            """Return static y4m plane payload."""
            return b"xy"

    class TwoFrameClip:
        """Clip producing two frames for multi-frame y4m write."""

        num_frames = 2

        def frames(self, prefetch=1):
            """Yield two frames and assert requested prefetch."""
            assert prefetch == 1
            return [PlaneFrame(), PlaneFrame()]

    clip = TwoFrameClip()
    fake_stdout = MagicMock()
    fake_stdout.fileno.return_value = 1

    with patch.object(native.sys, "stdout", fake_stdout):
        with patch.object(native.sys, "platform", "win32"):
            with patch.object(native.os, "write", side_effect=lambda _fd, data: len(data)):
                getattr(native, "_write_y4m_output")(clip, "Y4M\n")

    closing_stdout = SimpleNamespace(
        flush=lambda: None,
        fileno=lambda: 1,
        close=lambda: (_ for _ in ()).throw(OSError("close")),
    )
    with patch.object(native.sys, "stdout", closing_stdout):
        with patch.object(native.os, "write", side_effect=BrokenPipeError):
            with patch.object(native.sys, "exit", side_effect=SystemExit(0)):
                with pytest.raises(SystemExit):
                    getattr(native, "_write_y4m_output")(clip, "Y4M\n")


def test_vspipe_native_write_raw_setmode_error_and_nonzero_frame_branch():
    """Continue raw output when setmode fails and emit all frame bytes."""
    fake_vs = SimpleNamespace(get_outputs=lambda: {}, VideoOutputTuple=tuple, VideoNode=object)
    native = _load_vspipe_native(fake_vs)
    native.msvcrt = SimpleNamespace(setmode=MagicMock(side_effect=OSError("setmode")))

    class RawFrame:
        """Frame exposing one byte plane."""

        format = SimpleNamespace(num_planes=1)

        def __getitem__(self, _idx):
            """Return static plane payload."""
            return b"abc"

    class TwoFrameClip:
        """Clip producing two frames for multi-frame raw write."""

        num_frames = 2

        def frames(self, prefetch=1):
            """Yield two frames and assert requested prefetch."""
            assert prefetch == 1
            return [RawFrame(), RawFrame()]

    clip = TwoFrameClip()
    fake_out = io.BytesIO()
    fake_stdout = SimpleNamespace(buffer=fake_out, fileno=lambda: 1, close=lambda: None)

    with patch.object(native.sys, "platform", "win32"):
        with patch.object(native.sys, "stdout", fake_stdout):
            getattr(native, "_write_raw_output")(clip)

    assert fake_out.getvalue() == b"abcabc"


def test_vspipe_native_main_unsupported_format_exits():
    """Exit when output format is unsupported for native y4m writer."""

    class FakeVideoNode:
        """Simple clip holder for unsupported-format setup."""

        def __init__(self):
            self.width = 32
            self.height = 32
            self.num_frames = 1
            self.fps = SimpleNamespace(numerator=24, denominator=1)
            self.format = SimpleNamespace(id=999, name="UNKNOWN", num_planes=1)

    clip = FakeVideoNode()

    fake_vs = SimpleNamespace(
        get_outputs=lambda: {0: clip},
        VideoOutputTuple=tuple,
        VideoNode=FakeVideoNode,
        YUV420P8=1,
        YUV420P10=2,
        YUV420P16=3,
        YUV422P10=4,
        YUV444P10=5,
    )
    native = _load_vspipe_native(fake_vs)

    with patch.object(native.sys, "argv", ["vspipe_native", "ok.vpy"]):
        with patch.object(native.os.path, "exists", return_value=True):
            with patch.object(native.runpy, "run_path"):
                with patch.object(native.sys, "exit", side_effect=SystemExit(1)):
                    with pytest.raises(SystemExit):
                        native.main()


def test_vspipe_native_import_fallback_without_msvcrt_or_numpy(monkeypatch):
    """Import fallback keeps optional modules unset when unavailable."""

    real_import = builtins.__import__
    importlib.invalidate_caches()

    sys.modules.pop("numpy", None)

    fake_vs_module = SimpleNamespace(
        get_outputs=lambda: {},
        VideoOutputTuple=tuple,
        VideoNode=object,
        YUV420P8=1,
        YUV420P10=2,
        YUV420P16=3,
        YUV422P10=4,
        YUV444P10=5,
        core=SimpleNamespace(num_threads=1),
        __spec__=ModuleSpec("vapoursynth", loader=None),
    )

    def fake_import(name, globals_=None, locals_=None, fromlist=(), level=0):
        if name in {"msvcrt", "numpy"}:
            raise ImportError(name)
        if name == "vapoursynth":
            return fake_vs_module
        return real_import(name, globals_, locals_, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    try:
        module = importlib.import_module("modules.runtime.vspipe_native")
        module = importlib.reload(module)

        assert module.msvcrt is None
        assert module.np is None
    finally:
        sys.modules.pop("modules.runtime.vspipe_native", None)
