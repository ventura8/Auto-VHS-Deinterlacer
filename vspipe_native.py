import sys
import os
import vapoursynth as vs  # type: ignore


def main():
    if len(sys.argv) < 2:
        sys.stderr.write("Usage: python vspipe_native.py script.vpy\n")
        sys.exit(1)

    script_path = sys.argv[1]

    # Check if script exists
    if not os.path.exists(script_path):
        sys.stderr.write(f"Error: Script not found: {script_path}\n")
        sys.exit(1)

    # Execute Script
    # We must set sys.path to script dir so imports work?
    sys.path.append(os.path.dirname(os.path.abspath(script_path)))

    try:
        with open(script_path, "r", encoding="utf-8") as f:
            script_content = f.read()

        exec(script_content, globals())
    except Exception as e:
        sys.stderr.write(f"Error executing script: {e}\n")
        sys.exit(1)

    # Validate Output
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

    # Print Info to Stderr (for main script to parse if needed)
    sys.stderr.write(f"Output Info: {clip.width}x{clip.height} {clip.format.name} {clip.num_frames} frames\n")
    sys.stderr.flush()

    # Y4M Header Construction
    # Assumes valid YUV420P16 output as per auto_deinterlancer script
    # YUV4MPEG2 W<w> H<h> F<num>:<den> Ip A0:0 C<colorspace>

    colorspace = "C420p16"  # Default for our pipeline
    if clip.format.id == vs.YUV420P8:
        colorspace = "C420"
    elif clip.format.id == vs.YUV420P10:
        colorspace = "C420p10"
    elif clip.format.id == vs.YUV420P16:
        colorspace = "C420p16"
    elif clip.format.id == vs.YUV422P10:
        colorspace = "C422p10"
    elif clip.format.id == vs.YUV444P10:
        colorspace = "C444p10"

    width = clip.width
    height = clip.height
    fps_num = clip.fps.numerator
    fps_den = clip.fps.denominator

    header = f"YUV4MPEG2 W{width} H{height} F{fps_num}:{fps_den} Ip A0:0 {colorspace}\n"

    # [PERFORMANCE] Try to use numpy for efficient memory access
    try:
        import numpy as np
        use_numpy = True
    except ImportError:
        use_numpy = False

    # Write Frames
    try:
        if sys.platform == "win32":
            import msvcrt
            msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)

        out = sys.stdout.buffer

        # Write Y4M Header
        out.write(header.encode("utf-8"))

        frame_marker = b"FRAME\n"

        for n in range(clip.num_frames):
            frame = clip.get_frame(n)

            # Write Frame Marker
            out.write(frame_marker)

            for p in range(frame.format.num_planes):
                # [PERFORMANCE] Try to write plane directly if numpy is available
                if use_numpy:
                    # numpy.asarray on memoryview is very fast (zero-copy if contiguous)
                    # If non-contiguous, numpy will make a contiguous copy efficiently in C
                    arr = np.asarray(frame[p])
                    out.write(arr.tobytes())
                else:
                    # [FALLBACK] frame[p] may be non-contiguous due to padding.
                    # Convert to bytes to ensure strict C-contiguous buffer for stdout.write
                    out.write(bytes(frame[p]))

    except BrokenPipeError:
        sys.stderr.write("Broken Pipe - Consumer closed connection.\n")
        sys.exit(0)
    except Exception as e:
        sys.stderr.write(f"Error writing frame: {e}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
