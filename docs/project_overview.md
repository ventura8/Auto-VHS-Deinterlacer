# Project Overview

## Goal
**Auto-VHS-Deinterlacer** is a studio-grade automation pipeline designed to modernize VHS and analog video captures. It addresses three critical problems in analog archiving:
1.  **Deinterlacing**: Converting interlaced (480i/576i) footage to progressive using the best algorithms available (QTGMC).
2.  **Audio Drift**: Automatically correcting the "progressive audio drift" caused by imperfect capture cards or frame rate mismatches.

## Core Technologies
- **Python 3.10+**: Orchestration logic.
- **VapourSynth**: The core frame server.
- **FFmpeg**: Encoding and muxing engine.
- **QTGMC**: The "gold standard" for traditional deinterlacing.

## Modes
| Mode | Description | Hardware Reqs | Target Use Case |
| :--- | :--- | :--- | :--- |
| **QTGMC** | Archival-quality traditional deinterlacing ("Very Slow" Preset). | CPU / Any GPU | 99% of archives. Maximum reliability. |

## File Structure
- `auto_deinterlancer.py`: Thin entry point wrapper.
- `modules/`: Core package containing orchestrated logic.
  - `config.py`: Hardware-aware settings and `.yaml` loading.
  - `pipeline.py`: Main video processing pipeline.
  - `vspipe.py`: VapourSynth script generation and metadata retrieval.
  - `utils.py`: Logging, progress tracking, and OS-level utilities.
- `install.ps1`: Portable environment installer.
- `start.bat`: Drag & Drop launcher.
- `config.yaml`: User settings.
- `run_tests.ps1`: Automated test launcher.

## Testing & QA
To maintain studio reliability, this project uses a strict testing protocol:
- **Coverage**: 90% minimum code coverage required.
- **Tools**: `pytest` for logic, `flake8` for style, `mypy` for types.
- **CI/CD**: GitHub Actions pipeline runs on every push.
