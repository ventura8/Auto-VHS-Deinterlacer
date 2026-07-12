"""Unit tests for native vspipe helpers and havsfunc patching utilities."""

import builtins
import importlib
import io
import sys
from importlib.machinery import ModuleSpec
from types import SimpleNamespace
from unittest.mock import MagicMock, mock_open, patch

import pytest

from modules.core import patch_havsfunc


def _load_vspipe_native(fake_vs):
    """Reload vspipe_native with a fake vapoursynth module injected."""
    with patch.dict(sys.modules, {"vapoursynth": fake_vs}):
        native = importlib.import_module("modules.runtime.vspipe_native")

        return importlib.reload(native)


def test_patch_havsfunc_missing_file_exits_cleanly():
    """Exit successfully and print information when the target file is missing."""

    with patch("modules.core.patch_havsfunc.os.path.exists", return_value=False):
        with patch("modules.core.patch_havsfunc.sys.exit", side_effect=SystemExit(0)) as mock_exit:
            with patch("builtins.print") as mock_print:
                with pytest.raises(SystemExit):
                    patch_havsfunc.main()

    mock_exit.assert_called_once_with(0)
    assert mock_print.called


def test_patch_havsfunc_applies_replacements_and_writes():
    """Apply text replacements and write patched havsfunc content."""

    original = (
        "vs.get_core()\n"
        "f(a, _global = x)\n"
        "g(a, _lambda = y)\n"
        "def QTGMC(opencl=False):\n"
        "    return 1\n"
        "def QTGMC_Interpolate(opencl=False):\n"
        "    myNNEDI3 = core.nnedi3cl.NNEDI3CL\n"
        "    tmp = 0\n"
        "    myEEDI3 = core.eedi3m.EEDI3CL\n"
        "def helper(a, opencl):\n"
        "    return TFF, opencl)\n"
        "def helper2():\n"
        "    return TFF=TFF, opencl=opencl)\n"
        "def helper3():\n"
        "    return MatchEnhance, TFF, opencl)\n"
        "myNNEDI3 = core.nnedi3cl.NNEDI3CL\n"
        "myEEDI3 = core.eedi3m.EEDI3CL\n"
    )

    m_open = mock_open(read_data=original)

    with patch("modules.core.patch_havsfunc.os.path.exists", return_value=True):
        with patch("builtins.open", m_open):
            with patch("builtins.print"):
                patch_havsfunc.main()

    written = "".join(call.args[0] for call in m_open().write.call_args_list)
    assert "vs.core" in written
    assert "_global" not in written
    assert "_lambda" not in written
    assert "device=0" in written
    assert "functools.partial(core.nnedi3cl.NNEDI3CL, device=device)" in written


def test_patch_havsfunc_replace_helpers_cover_warning_and_required_paths():
    """Cover helper replacement warning and required-error paths."""

    updated, count = getattr(patch_havsfunc, "_replace_text")("foo", "demo", "foo", "bar")
    assert updated == "bar"
    assert count == 1

    with patch("builtins.print") as mock_print:
        unchanged, count = getattr(patch_havsfunc, "_replace_text")("foo", "missing", "zzz", "bar")
    assert unchanged == "foo"
    assert count == 0
    assert mock_print.called

    with pytest.raises(RuntimeError):
        getattr(patch_havsfunc, "_replace_text")("foo", "required", "zzz", "bar", required=True)

    updated_regex, count_regex = getattr(patch_havsfunc, "_replace_regex")("ab12", "rx", r"\d+", "")
    assert updated_regex == "ab"
    assert count_regex == 1

    with patch("builtins.print") as mock_print:
        unchanged_regex, count_regex = getattr(patch_havsfunc, "_replace_regex")("ab", "missing_rx", r"\d+", "")
    assert unchanged_regex == "ab"
    assert count_regex == 0
    assert mock_print.called

    with pytest.raises(RuntimeError):
        getattr(patch_havsfunc, "_replace_regex")("ab", "required_rx", r"\d+", "", required=True)


def test_patch_havsfunc_handles_multiline_docstring_and_future_import_insertion():
    """Insert functools import after a module docstring and future imports."""

    original = (
        "#!/usr/bin/env python\n"
        '"""module doc\n'
        "still doc\n"
        '"""\n'
        "from __future__ import annotations\n"
        "vs.get_core()\n"
        "def QTGMC(opencl=False):\n"
        "    return 1\n"
    )

    m_open = mock_open(read_data=original)
    with patch("modules.core.patch_havsfunc.os.path.exists", return_value=True):
        with patch("builtins.open", m_open):
            with patch("builtins.print"):
                patch_havsfunc.main()

    written = "".join(call.args[0] for call in m_open().write.call_args_list)
    assert "import functools" in written
    assert written.index("from __future__ import annotations") < written.index("import functools")


def test_patch_havsfunc_skips_legacy_block_when_device_already_present():
    """Skip legacy patch section when device argument already exists."""

    original = "import functools\ndef QTGMC(opencl=False, device=0):\n    return 1\n"

    m_open = mock_open(read_data=original)
    with patch("modules.core.patch_havsfunc.os.path.exists", return_value=True):
        with patch("builtins.open", m_open):
            with patch("builtins.print") as mock_print:
                patch_havsfunc.main()

    printed_messages = [call.args[0] for call in mock_print.call_args_list]
    assert any("skipping legacy device patch block" in msg for msg in printed_messages)
    assert any("Patched havsfunc.py" in msg for msg in printed_messages)


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

    sys.modules.pop("modules.runtime.vspipe_native", None)
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

    module = importlib.import_module("modules.runtime.vspipe_native")
    module = importlib.reload(module)

    assert module.msvcrt is None
    assert module.np is None
