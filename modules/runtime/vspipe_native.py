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


def _write_y4m_output(clip, header):
    """Write the video clip to stdout in Y4M format."""
    use_numpy = np is not None

    try:
        # Flush standard Python buffers before changing mode or writing raw bytes.
        sys.stdout.flush()
        fd = sys.stdout.fileno()

        if sys.platform == "win32":
            if msvcrt is not None:
                msvcrt.setmode(fd, O_BINARY_MODE)

        sys.stderr.write(f"Writing Y4M Header: {len(header)} bytes\n")
        _write_all(fd, header.encode("utf-8"))

        frame_marker = b"FRAME\n"
        sys.stderr.write("Starting frame encoding loop...\n")

        for n, frame in enumerate(_iter_frames(clip)):
            _write_all(fd, frame_marker)

            for p in range(frame.format.num_planes):
                plane = frame[p]
                if use_numpy:
                    arr = np.asarray(plane)
                    _write_all(fd, arr.tobytes())
                else:
                    _write_all(fd, bytes(plane))

            if n % 100 == 0:
                sys.stderr.write(f"Wrote frame {n}/{clip.num_frames}\n")

    except BrokenPipeError:
        sys.stderr.write("Broken Pipe - Consumer closed connection.\n")
        try:
            sys.stdout.close()
        except OSError:
            pass
        sys.exit(0)
    except (OSError, RuntimeError, ValueError, TypeError) as error:
        sys.stderr.write(f"Error writing frame: {error}\n")
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)


def _write_raw_output(clip):
    """Write raw video planes to stdout without headers."""
    try:
        if sys.platform == "win32" and msvcrt is not None:
            try:
                msvcrt.setmode(sys.stdout.fileno(), O_BINARY_MODE)
            except (AttributeError, OSError, ValueError):
                pass

        out = sys.stdout.buffer
        sys.stderr.write("Starting RAW frame encoding loop (using sys.stdout.buffer)...\n")

        for n, frame in enumerate(_iter_frames(clip)):
            for p in range(frame.format.num_planes):
                out.write(bytes(frame[p]))

            if n % 100 == 0:
                sys.stderr.write(f"Wrote frame {n}/{clip.num_frames}\n")
                out.flush()

    except BrokenPipeError:
        sys.stderr.write("Broken Pipe - Consumer closed connection.\n")
        try:
            sys.stdout.close()
        except OSError:
            pass
        sys.exit(0)
    except (OSError, RuntimeError, ValueError, TypeError) as error:
        sys.stderr.write(f"Error writing frame: {error}\n")
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)


def main():
    """Execute a VPY script and stream the first output clip to stdout."""
    args = sys.argv[1:]
    raw_mode = False

    if "--raw" in args:
        raw_mode = True
        args.remove("--raw")

    if len(args) < 1:
        sys.stderr.write("Usage: python -m modules.runtime.vspipe_native script.vpy [--raw]\n")
        sys.exit(1)

    script_path = args[0]
    if not os.path.exists(script_path):
        sys.stderr.write(f"Error: Script not found: {script_path}\n")
        sys.exit(1)

    sys.path.append(os.path.dirname(os.path.abspath(script_path)))

    try:
        runpy.run_path(script_path, run_name="__vapoursynth_script__")
    except (OSError, RuntimeError, ValueError) as error:
        sys.stderr.write(f"Error executing script: {error}\n")
        sys.exit(1)

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

    sys.stderr.write(f"Output Info: {clip.width}x{clip.height} {clip.format.name} {clip.num_frames} frames\n")
    sys.stderr.flush()

    if raw_mode:
        _write_raw_output(clip)
    else:
        colorspaces = {
            vs.YUV420P8: "C420",
            vs.YUV420P10: "C420p10",
            vs.YUV420P16: "C420p16",
            vs.YUV422P10: "C422p10",
            vs.YUV444P10: "C444p10",
        }
        colorspace = colorspaces.get(clip.format.id)
        if colorspace is None:
            sys.stderr.write(f"Error: Unsupported clip format for Y4M output: {clip.format.name} (id={clip.format.id})\n")
            sys.exit(1)
        header = f"YUV4MPEG2 W{clip.width} H{clip.height} F{clip.fps.numerator}:{clip.fps.denominator} Ip A0:0 {colorspace}\n"
        _write_y4m_output(clip, header)


if __name__ == "__main__":
    main()
