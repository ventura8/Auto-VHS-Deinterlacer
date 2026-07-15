"""Native VapourSynth output writer used as a Python fallback for vspipe."""

import os
import runpy
import sys
import traceback

try:
    import msvcrt
except ImportError:
    msvcrt = None

try:
    import numpy as np
except ImportError:
    np = None

import vapoursynth as vs

O_BINARY_MODE = getattr(os, "O_BINARY", 0)


def _get_y4m_colorspaces():
    """Return the supported Y4M colorspace map for the current VapourSynth module."""
    colorspaces = {}
    for attr_name, token in (
        ("YUV420P8", "C420"),
        ("YUV420P10", "C420p10"),
        ("YUV420P16", "C420p16"),
        ("YUV422P10", "C422p10"),
        ("YUV444P10", "C444p10"),
    ):
        attr_value = getattr(vs, attr_name, None)
        if attr_value is not None:
            colorspaces[attr_value] = token
    return colorspaces


def _iter_frames(clip):
    """Yield frames in order using VapourSynth's concurrent prefetch API."""
    prefetch = max(1, getattr(getattr(vs, "core", None), "num_threads", 1))
    return clip.frames(prefetch=prefetch)


def _write_all(fd, data):
    """Write the full byte buffer to fd, retrying partial writes."""
    view = memoryview(data)
    offset = 0
    while offset < len(view):
        count = os.write(fd, view[offset:])
        if count <= 0:
            raise OSError("Short write while streaming output")
        offset += count


def _set_stdout_binary_mode():
    """Switch stdout to binary mode when running on Windows."""
    if sys.platform != "win32" or msvcrt is None:
        return

    try:
        stdout_fd = sys.stdout.fileno()
    except (AttributeError, OSError, ValueError):
        return

    try:
        msvcrt.setmode(stdout_fd, O_BINARY_MODE)
    except OSError:
        return


def _write_frame_planes(fd, frame, use_numpy):
    """Write all planes for a frame to a raw file descriptor."""
    for plane_index in range(frame.format.num_planes):
        plane = frame[plane_index]
        if use_numpy:
            _write_all(fd, np.asarray(plane).tobytes())
            continue
        _write_all(fd, bytes(plane))


def _write_buffered_planes(out, frame):
    """Write all planes for a frame to a buffered stream."""
    for plane_index in range(frame.format.num_planes):
        out.write(bytes(frame[plane_index]))


def _log_frame_progress(frame_index, total_frames, flush_output=None):
    """Emit periodic progress updates while streaming frames."""
    completed_frame = frame_index + 1
    if completed_frame % 100 != 0:
        return
    sys.stderr.write(f"Wrote frame {completed_frame}/{total_frames}\n")
    if flush_output is not None:
        flush_output()


def _exit_broken_pipe():
    """Handle an expected broken pipe when the consumer exits early."""
    sys.stderr.write("Broken Pipe - Consumer closed connection.\n")
    try:
        sys.stdout.close()
    except OSError:
        pass
    sys.exit(0)


def _exit_write_error(error):
    """Report a write failure and terminate with an error."""
    sys.stderr.write(f"Error writing frame: {error}\n")
    traceback.print_exc(file=sys.stderr)
    sys.exit(1)


def _write_y4m_output(clip, header):
    """Write the video clip to stdout in Y4M format."""
    use_numpy = np is not None

    try:
        sys.stdout.flush()
        fd = sys.stdout.fileno()
        _set_stdout_binary_mode()

        sys.stderr.write(f"Writing Y4M Header: {len(header)} bytes\n")
        _write_all(fd, header.encode("utf-8"))

        frame_marker = b"FRAME\n"
        sys.stderr.write("Starting frame encoding loop...\n")

        for frame_index, frame in enumerate(_iter_frames(clip)):
            _write_all(fd, frame_marker)
            _write_frame_planes(fd, frame, use_numpy)
            _log_frame_progress(frame_index, clip.num_frames)

    except BrokenPipeError:
        _exit_broken_pipe()
    except (OSError, RuntimeError, ValueError, TypeError) as error:
        _exit_write_error(error)


def _write_raw_output(clip):
    """Write raw video planes to stdout without headers."""
    try:
        _set_stdout_binary_mode()

        out = sys.stdout.buffer
        sys.stderr.write("Starting RAW frame encoding loop (using sys.stdout.buffer)...\n")

        for frame_index, frame in enumerate(_iter_frames(clip)):
            _write_buffered_planes(out, frame)
            _log_frame_progress(frame_index, clip.num_frames, out.flush)

    except BrokenPipeError:
        _exit_broken_pipe()
    except (OSError, RuntimeError, ValueError, TypeError) as error:
        _exit_write_error(error)


def _parse_cli_args(args):
    """Parse module CLI arguments into script path and raw mode."""
    raw_mode = "--raw" in args
    script_args = [arg for arg in args if arg != "--raw"]
    if not script_args:
        sys.stderr.write("Usage: python -m modules.runtime.vspipe_native script.vpy [--raw]\n")
        sys.exit(1)
    return script_args[0], raw_mode


def _ensure_script_exists(script_path):
    """Validate that the provided VPY script exists."""
    if not os.path.exists(script_path):
        sys.stderr.write(f"Error: Script not found: {script_path}\n")
        sys.exit(1)


def _run_vpy_script(script_path):
    """Execute the VPY script in an isolated runpy context."""
    sys.path.append(os.path.dirname(os.path.abspath(script_path)))
    try:
        runpy.run_path(script_path, run_name="__vapoursynth_script__")
    except (OSError, RuntimeError, ValueError) as error:
        sys.stderr.write(f"Error executing script: {error}\n")
        sys.exit(1)


def _resolve_output_clip():
    """Return the first VapourSynth output clip and validate its type."""
    outputs = vs.get_outputs()
    if not outputs:
        sys.stderr.write("Error: No output node set in script!\n")
        sys.exit(1)

    clip = outputs[0]
    if isinstance(clip, vs.VideoOutputTuple):
        clip = clip.clip
    if not isinstance(clip, vs.VideoNode):
        sys.stderr.write("Error: Output is not a video clip.\n")
        sys.exit(1)
    return clip


def _get_y4m_colorspace(clip):
    """Resolve the Y4M colorspace token for the clip format."""
    colorspace = _get_y4m_colorspaces().get(clip.format.id)
    if colorspace is None:
        sys.stderr.write(f"Error: Unsupported clip format for Y4M output: {clip.format.name} (id={clip.format.id})\n")
        sys.exit(1)
    return colorspace


def _build_y4m_header(clip, colorspace):
    """Build the Y4M stream header for the clip."""
    return f"YUV4MPEG2 W{clip.width} H{clip.height} F{clip.fps.numerator}:{clip.fps.denominator} Ip A0:0 {colorspace}\n"


def main():
    """Execute a VPY script and stream the first output clip to stdout."""
    script_path, raw_mode = _parse_cli_args(sys.argv[1:])
    _ensure_script_exists(script_path)
    _run_vpy_script(script_path)
    clip = _resolve_output_clip()

    sys.stderr.write(f"Output Info: {clip.width}x{clip.height} {clip.format.name} {clip.num_frames} frames\n")
    sys.stderr.flush()

    if raw_mode:
        _write_raw_output(clip)
        return

    colorspace = _get_y4m_colorspace(clip)
    _write_y4m_output(clip, _build_y4m_header(clip, colorspace))


if __name__ == "__main__":
    main()
