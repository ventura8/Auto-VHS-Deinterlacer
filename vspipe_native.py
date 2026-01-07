import sys
import os
import vapoursynth as vs  # type: ignore


def _write_y4m_output(clip, header):
    """Writes the video clip to stdout in Y4M format."""
    try:
        import numpy as np
        use_numpy = True
    except ImportError:
        use_numpy = False

    try:
        # Flush standard python buffers before changing mode or writing raw
        sys.stdout.flush()
        
        fd = sys.stdout.fileno()
        
        if sys.platform == "win32":
            import msvcrt
            msvcrt.setmode(fd, os.O_BINARY)

        # Write header
        sys.stderr.write(f"Writing Y4M Header: {len(header)} bytes\n")
        os.write(fd, header.encode("utf-8"))
        
        frame_marker = b"FRAME\n"
        sys.stderr.write("Starting frame encoding loop...\n")

        for n in range(clip.num_frames):
            frame = clip.get_frame(n)
            
            # Write 'FRAME\n'
            os.write(fd, frame_marker)

            for p in range(frame.format.num_planes):
                plane = frame[p]
                if use_numpy:
                    # numpy.asarray on memoryview is very fast
                    arr = np.asarray(plane)
                    os.write(fd, arr.tobytes())
                else:
                    # Fallback to bytes() copy
                    os.write(fd, bytes(plane))
            
            if n % 100 == 0:
                 sys.stderr.write(f"Wrote frame {n}/{clip.num_frames}\n")

    except BrokenPipeError:
        sys.stderr.write("Broken Pipe - Consumer closed connection.\n")
        # Python flushes on exit, so ensure we don't double-flush or error
        try:
            sys.stdout.close()
        except Exception: 
            pass
        sys.exit(0)
    except Exception as e:
        sys.stderr.write(f"Error writing frame: {e}\n")
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)


def main():
    args = sys.argv[1:]
    raw_mode = False
    
    if "--raw" in args:
        raw_mode = True
        args.remove("--raw")

    if len(args) < 1:
        sys.stderr.write("Usage: python vspipe_native.py script.vpy [--raw]\n")
        sys.exit(1)

    script_path = args[0]
    if not os.path.exists(script_path):
        sys.stderr.write(f"Error: Script not found: {script_path}\n")
        sys.exit(1)

    sys.path.append(os.path.dirname(os.path.abspath(script_path)))

    try:
        with open(script_path, "r", encoding="utf-8") as f:
            script_content = f.read()
        exec(script_content, globals())
    except Exception as e:
        sys.stderr.write(f"Error executing script: {e}\n")
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
        # Y4M Header Construction
        colorspaces = {
            vs.YUV420P8: "C420", vs.YUV420P10: "C420p10", vs.YUV420P16: "C420p16",
            vs.YUV422P10: "C422p10", vs.YUV444P10: "C444p10"
        }
        colorspace = colorspaces.get(clip.format.id, "C420p16")
        header = f"YUV4MPEG2 W{clip.width} H{clip.height} F{clip.fps.numerator}:{clip.fps.denominator} Ip A0:0 {colorspace}\n"
        _write_y4m_output(clip, header)


def _write_raw_output(clip):
    """Writes raw video planes to stdout (no headers)."""
    try:
        # Standard binary output buffer
        out = sys.stdout.buffer
        
        sys.stderr.write("Starting RAW frame encoding loop (using sys.stdout.buffer)...\n")

        for n in range(clip.num_frames):
            frame = clip.get_frame(n)
            
            for p in range(frame.format.num_planes):
                # Write plane data directly
                out.write(bytes(frame[p]))
            
            if n % 100 == 0:
                 sys.stderr.write(f"Wrote frame {n}/{clip.num_frames}\n")
                 out.flush()

    except BrokenPipeError:
        sys.stderr.write("Broken Pipe - Consumer closed connection.\n")
        try:
            sys.stdout.close()
        except Exception: 
            pass
        sys.exit(0)
    except Exception as e:
        sys.stderr.write(f"Error writing frame: {e}\n")
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
