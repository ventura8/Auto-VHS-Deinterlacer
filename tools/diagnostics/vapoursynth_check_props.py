"""Manual VapourSynth probe for local diagnostics.

Run directly when you need a quick environment sanity check.
"""

try:
    import vapoursynth as vs

    core = vs.core
    clip = core.std.BlankClip(width=640, height=480, fpsnum=30000, fpsden=1001, length=1000)
    clip.set_output()
except Exception as e:
    print(e)
