# Project Overview

## Goal

**Auto-VHS-Deinterlacer** is a studio-grade automation pipeline designed to modernize VHS and analog video captures. It addresses three critical problems in analog archiving:

1. **Deinterlacing**: Converting interlaced (480i/576i) footage to progressive using the best algorithms available (QTGMC).
1. **Audio Drift**: Automatically correcting the "progressive audio drift" caused by imperfect capture cards or frame rate mismatches.

## Core Technologies

- **Python 3.12**: Orchestration logic.
- **VapourSynth**: The core frame server.
- **FFmpeg**: Encoding and muxing engine.
- **QTGMC**: The "gold standard" for traditional deinterlacing.

## Modes

| Mode | Description | Hardware Reqs | Target Use Case |
| :--- | :--- | :--- | :--- |
| **QTGMC** | Archival-quality traditional deinterlacing ("Very Slow" Preset). | CPU / Any GPU | 99% of archives. Maximum reliability. |

## File Structure

- `auto_deinterlancer.py`: Thin entry point wrapper.
- `modules/core/`: Shared configuration and runtime-agnostic helpers.
  - `config.py`: Hardware-aware settings and `.yaml` loading.
  - `utils.py`: Logging, progress tracking, and OS-level utilities.
  - `patch_havsfunc.py`: Setup-time compatibility patch for bundled `havsfunc`.
- `modules/runtime/`: Pipeline orchestration and VapourSynth/FFmpeg integration.
  - `pipeline.py`: Main video processing pipeline.
  - `vspipe.py`: VapourSynth script generation and metadata retrieval.
  - `vspipe_native.py`: Native Python fallback output writer.
- `.\install.ps1`: Local installer that provisions a pip-backed VapourSynth runtime.
- `start.bat`: Drag & Drop launcher; supports both `.venv` and `.VENV` and exits
  cleanly when interactive input is cancelled.
- `config.yaml`: User settings.
- `.\run_pipeline_localy.ps1`: Automated lint/test/coverage pipeline.

## Testing & QA

To maintain studio reliability, this project uses a strict testing protocol:

- **Coverage**: Every Python module must stay above 90% coverage, and total repository coverage must stay above 90%.
- **Tools**: `pytest` for logic, `ruff` and `flake8` for lint/style, and `pylint` for static analysis.
- **CI/CD**: GitHub Actions pipeline runs on every push.
