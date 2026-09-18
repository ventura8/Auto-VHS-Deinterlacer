# Architecture Overview

## High-Level Layout

- `auto_deinterlancer.py`: entrypoint and compatibility wrapper.
- `modules/core/config.py`: configuration loading and hardware detection.
- `modules/core/utils.py`: logging, environment setup, command helpers, and utility functions.
- `modules/core/patch_havsfunc.py`: setup-time compatibility patching for bundled `havsfunc` (documented exception to the core boundary rule).
- `modules/runtime/pipeline.py`: main deinterlace and encode orchestration.
- `modules/runtime/inputs.py`: input discovery from CLI arguments, folder scans, and the interactive prompt.
- `modules/runtime/encoders.py`: FFmpeg video-encoder argument selection, including the runtime AV1 CPU encoder probe.
- `modules/runtime/workspace.py`: per-video temp workspace (`<file name>.autovhs-tmp/`), segment plan, resume state, and cleanup.
- `modules/runtime/vspipe.py`: VapourSynth script generation and `vspipe` metadata queries.
- `modules/runtime/vspipe_native.py`: Python fallback writer for `vspipe`.
- `tests/unit/`, `tests/integration/`, `tests/native/`: coverage grouped by behavior area.
- `.github/scripts/generate_coverage_summary.py`: CI coverage report helper.

## Runtime Flow

1. Entry point loads configuration and environment helpers.
1. Hardware settings are detected from RAM, CPU, and GPU data.
1. A VapourSynth script is generated for the current source file.
1. `vspipe` or the native fallback streams frames into FFmpeg, one resumable segment at a time, inside the per-video workspace.
1. FFmpeg joins the segments with the source audio, the result is renamed into place, and the workspace folder is deleted.

## Design Boundaries

- `modules/core` owns shared support code and should stay runtime-agnostic, with one explicit exception: `modules/core/patch_havsfunc.py` for setup-time bundled `havsfunc` compatibility.
- `modules/runtime` owns pipeline control flow and external process orchestration.
- Tests should mock external tools at the module boundary, not by patching globals in unrelated modules.
