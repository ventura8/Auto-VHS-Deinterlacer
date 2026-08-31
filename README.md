# Auto-VHS-Deinterlacer

![Auto-VHS-Deinterlacer Banner](assets/banner.svg)

Studio-Reference VHS Restoration Pipeline

![Coverage](assets/coverage.svg)

Automated deinterlacing and audio synchronization tool for modernizing VHS
captures.

## 🛠️ Restoration Pipeline

```mermaid
flowchart TD
    %% Styling
    classDef input fill:#DAE2F9,stroke:#3F5F91,stroke-width:1px,color:#001B3E,rx:10,ry:10;
    classDef process fill:#DCE5DD,stroke:#526350,stroke-width:1px,color:#101E10,rx:5,ry:5;
    classDef output fill:#E1E2E6,stroke:#44474E,stroke-width:1.5px,color:#1A1C1E,rx:10,ry:10;

    Input([📼 VHS Capture]):::input

    subgraph Step1 ["Step 1: Setup & Analysis"]
        direction TB
        Gen[Script Gen] --> Check[Pre-Flight Info Check]
        Check --> Drift{"Calc Drift"}
    end

    subgraph Step2 ["Step 2: Processing"]
        direction TB
        Render[VSPipe Render] -->|Pipe| Encode["Encode + Sync + Mux"]:::process
    end

    Output([💾 Restored Master]):::output

    Input --> Step1
    Step1 --> Step2
    Step2 --> Output
```

## ⚡ Hardware Optimization

This tool automatically detects high-end hardware (for example, RTX 5090 and
Ryzen 9950X3D) to enable ULTRA profiles.

- CPU: Automatically scales threads to match your core count.
- RAM: Automatically adjusts cache based on available memory.

## 🚀 Installation & Usage

### 📦 Prebuilt Native Installers & Executables (GitHub Releases)

Download the official standalone application / package for your operating system from [Releases](https://github.com/ventura8/Auto-VHS-Deinterlacer/releases):

- **Windows**: Run `Auto-VHS-Deinterlacer-v<VERSION>.exe`
- **Debian / Ubuntu**: `sudo dpkg -i auto-vhs-deinterlacer_<VERSION>_amd64.deb`
- **Fedora / RHEL / openSUSE**: `sudo rpm -i auto-vhs-deinterlacer-<VERSION>-1.x86_64.rpm`
- **macOS**: Double-click `Auto-VHS-Deinterlacer-v<VERSION>-AppleSilicon.pkg` (or `-Intel.pkg`)

### 🛠️ Manual / Source Installation

#### Windows

- Install once: Right-click `.\install.ps1` and choose Run with PowerShell.
- Run: Drag and drop a video file onto `start.bat` or double-click `start.bat`.
  The launcher accepts either `.venv` or `.VENV`; if no path is supplied it opens
  the interactive prompt. Pressing Ctrl+C or sending EOF exits cleanly.

#### Linux & macOS

- Install once: `chmod +x install.sh && ./install.sh`
- Run: `./start.sh path/to/video.mp4` (or `auto-vhs-deinterlacer path/to/video.mp4` when installed via package)

### Docker & Virtualized Test Containers

- Ubuntu 26.04 (Real Dependencies): `./docker/run_docker_e2e.sh`
- Windows VM ([`dockurr/windows`](https://hub.docker.com/r/dockurr/windows)): `./docker/run_dockurr_tests.sh --windows`
- macOS VM ([`dockurr/macos`](https://hub.docker.com/r/dockurr/macos)): `./docker/run_dockurr_tests.sh --macos` (Restricted to genuine Apple hardware in compliance with Apple's macOS EULA; running macOS in containers/VMs on non-Apple hardware is subject to license restrictions.) Requires KVM access through native Docker Engine on a supported Linux host, or on Windows 11 with nested virtualization enabled. Docker Desktop on macOS does not expose the KVM device this container needs.

### Configuration

- Edit `config.yaml` to switch between `prores` and `av1`.

## 📋 Requirements

- Windows 10/11, Linux (Ubuntu, Debian, Arch, Fedora), or macOS (Apple Silicon & Intel)
- Python 3.12 (CPython 64-bit)
- FFmpeg 9.0: every installer bundles a static build into the local
  environment (Windows: `.VENV\Scripts`; Linux/macOS: `.venv/bin`, fetched from
  BtbN / evermeet). On macOS Apple Silicon (arm64), Rosetta 2 is required to run the
  bundled x86_64 build (`softwareupdate --install-rosetta`), or a native arm64 FFmpeg 9.0
  build can be placed in `.venv/bin` / system PATH. Set `AVD_SKIP_FFMPEG=1` to use
  system FFmpeg on any supported platform (for example, a full build with
  `libsvtav1` for CPU AV1 encoding).
- VapourSynth: on Windows `install.ps1` pulls the plugin DLLs via `vsrepo`; on
  Linux/macOS `install.sh` installs the `vapoursynth` wheel (bundles `vspipe`)
  and assembles the QTGMC plugin stack — `ffms2` is copied from the installed
  `libffms2` system library when present, and BestSource, fmtconv, mvtools,
  RemoveGrain, znedi3, EEDI3 and MiscFilters are compiled from source as a
  fallback. The source-build fallback needs a C/C++ toolchain plus
  `nasm`, `meson`, `ninja`, `autoconf`/`automake`/`libtool`, `pkg-config`,
  `cmake` and `git`; the installer auto-installs these via apt/pacman/dnf/brew.
  Set `AVD_SKIP_VS_PLUGINS=1` to skip the plugin build.

## Why this exists

Capturing VHS is messy.

1. Deinterlacing is hard: Standard FFmpeg filters like yadif and bwdif lose
   temporal detail or introduce jagged edges.
1. Audio sync drift: VHS captures often report 30.00fps vs 29.97fps, causing
   audio drift by the end of a tape.

This tool solves both automatically.

## ✨ Features

- Studio reference reliability with a self-contained local Python environment.
- Archival-grade QTGMC defaults with configurable settings in `config.yaml`.
- Smart drift correction with adaptive thresholding.
- Lossless audio workflow with PCM, AAC, and FLAC options.
- ISO 8601 logging with millisecond precision and timezone offsets.
- Real-time progress with ETA, timestamp, and speed.
- Zero-loss pipeline from VapourSynth to FFmpeg.
- Cross-platform support across Windows, Linux, and macOS with native and fallback modes.

## 🛠️ Development Requirements

- Operating System: Windows 10/11, Linux, or macOS
- Python 3.12
- Coverage policy:
  Maintain ≥90% line coverage per-file and repository-wide across product code (`auto_deinterlancer.py` and `modules/`) with branch coverage tracking; CI/automation scripts under `.github/scripts/` are validated via separate linters and metric gates.
- Local pipeline:
  Run `.\run_pipeline_localy.ps1` (PowerShell) or `./run_pipeline_localy.sh` (POSIX bash) before pushing.
- Dependency profiles:
  Local and CI quality-validation jobs (lint, unit, integration) use lightweight dependencies only.
  The containerised `ubuntu_docker_e2e` and `macos_e2e` jobs run real-dependency E2E tests;
  heavy CUDA and VapourSynth packages are reserved for those environments and production installs.

## 📦 Installation and Usage

1. Install one-time setup:
   - Windows: Right-click `.\install.ps1` and choose Run with PowerShell.
   - Linux / macOS: Run `./install.sh`.
   - The script will:
     - Create a secluded virtual environment (`.VENV` on Windows, `.venv` on Linux / macOS).
     - Install main runtime dependencies.
     - Download `havsfunc.py` r33, static `FFmpeg 9.0`, and bootstrap archives with SHA-256 integrity verification, automatic deletion of corrupt files, and retry loops.
     - Apply device-aware compatibility patches.
     - Generate a `start.bat` / `start.sh` launcher.
1. Run:
   - Windows: Drag and drop files onto `start.bat`, or run `start.bat <video>`.
   - Linux / macOS: Execute `./start.sh <video>`.
1. Processing:
   - The tool initializes, verifies hardware, and starts batch processing.
   - Outputs are saved beside source files with `_deinterlaced` suffixes.

## 🧠 Technical Details

The script generates a VapourSynth script (`.vpy`) on the fly with defensive
plugin loading.

1. Ingest: Load video via FFMS2.
1. Processing: Apply QTGMC Placebo and archival settings.
1. Single-pass processing:
   - Efficiency: Pipe video directly from VapourSynth to FFmpeg.
   - Sync: Calculate drift before encoding and apply `atempo` as needed.
   - Encoding:
     - ProRes 422 HQ (10-bit) for archival.
     - Optional AV1 for high-efficiency output.

## 📄 License

MIT

## ✅ Local Quality Gate

Run the full local validation pipeline:

```powershell
.\run_pipeline_localy.ps1
```

Or on Linux / macOS:

```bash
./run_pipeline_localy.sh
```

This validates Ruff, Flake8, Pylint, Markdown linting, tests with coverage,
PowerShell linting, Taplo TOML linting, Bandit security scanning,
pip-audit dependency scanning, Black formatting, isort import ordering,
Radon quality gates, coverage threshold enforcement, and regeneration of
`assets/coverage.svg`.
