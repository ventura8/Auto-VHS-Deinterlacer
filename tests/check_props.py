import vapoursynth as vs  # type: ignore
try:
    core = vs.core
    clip = core.std.BlankClip(width=640, height=480, fpsnum=30000, fpsden=1001, length=1000)
    clip.set_output()
except Exception as e:
    print(e)
