# Pipeline Logic

The `auto_deinterlancer.py` script executes a strictly ordered 4-stage pipeline for each video file.

## Step 1: Hardware Detection (Pre-Flight)

Before processing begins, the script:

1. **Checks CPU Cores**: Uses `os.cpu_count()` to determine optimal thread count.
1. **Checks RAM**: Uses `GlobalMemoryStatusEx` to detect system RAM.
   - **High-Performance Profile**: If RAM > 48GB, allocates 50% for cache.
   - **Mid/Standard Profile**: If RAM > 24GB, allocates 35% for cache.
1. **Checks GPU**: Scans for `nvidia-smi`, verifies the VapourSynth OpenCL QTGMC
   plugins, and performs a one-frame FFmpeg AV1 NVENC probe before enabling NVENC.

## Step 2: Single-Pass Analysis & Processing

### 2a. Script & Analysis

1. **Script Generation**: A VapourSynth (`.vpy`) script is created (dependency-injected with local `.venv`).
1. **Pre-Flight Check**: The script is dry-run (`vspipe --info`) to extract exact Frame Count and FPS.
   - **Drift Calculation**: Compares Source Audio Duration vs. Script Video Duration.
   - **Correction Logic**:
     - Drift < 10ms: Ignored.
     - Drift > 1.5%: Ignored (safety cap).
     - Valid Drift: Calculated as `speed_factor` for real-time correction.

### 2b. Segmented Execution (Resumable)

The clip is encoded in fixed-length segments (`resume_segment_minutes`,
default 5). For each segment the pipeline runs one consolidated command:
`VSPipe --start N --end M (raw video) | FFmpeg (video only)`

- **Video Flow**: Deinterlaced frames are piped directly to FFmpeg and written
  as `segments/seg_NNNN.part.<ext>`; the file is renamed to `seg_NNNN.<ext>`
  only after both processes exit cleanly.
- **Long tapes**: the `vspipe --info` probe's hang guard scales with the source
  size (30 min + 5 min/GB) because it builds the index on first run. After the
  first encoded segment the pipeline projects the output size and the peak disk
  use during the join (segments and the muxed part file coexist, so about twice
  the output) and warns when the workspace drive is short; the join itself is
  refused, with the segments kept for resume, if the drive cannot hold it.
- **Resume**: Segments already present and valid are skipped, so a rerun after
  a power cut continues from the last finished segment. The workspace stores
  the source identity (path, size, nanosecond mtime and a digest of sixteen
  1 MiB samples of the content) and a fingerprint of the settings that shape
  the video.
  A replaced source discards the indexes and segments before anything is
  probed; changed settings discard the segments. A segment that cannot be
  deleted fails the job instead of being reused under the new fingerprint.
- **Encoding**:
  - **ProRes**: Encodes to ProRes 422 HQ (10-bit).
  - **AV1**: Transcodes with NVENC AV1 only when the probe succeeds; otherwise it
    uses the first AV1 CPU encoder the active FFmpeg actually provides
    (SVT-AV1, then libaom).

### 2c. Final Mux

Once every segment exists, FFmpeg concatenates them with stream copy (no
re-encode) and muxes the source audio, applying `atempo`/`adelay` when drift
correction or a manual offset is configured. The result is written inside the
workspace and then atomically renamed to the final output name.

## Step 3: Robustness & Cleanup

The pipeline is designed to be "Power Loss Tolerant" and to never leave temp
files behind.

- **One Workspace Per Video**: Every temporary or cache file lives inside
  `<source name>.autovhs-tmp/` next to the source:
  `restore.vpy` (generated script), `index/` (ffms2 / L-SMASH / BestSource
  indexes), `segments/` (finished video segments), `segments.txt` (concat
  list), `state.json` (settings fingerprint) and the muxed `*_part.<ext>`
  file. Apart from that one workspace folder, nothing is written beside the
  source, and nothing at all is written to the system temp folder.
- **Resume Capability**: Checks if the final output exists to avoid
  re-processing, and otherwise reuses finished segments from the workspace.
  Interrupted `*.part.*` files are deleted at every start.
- **Auto-Cleanup**: The whole workspace folder is deleted as soon as the final
  output is in place, or when a valid output already exists. On failure the
  workspace is kept and the log tells you to re-run the same file to resume.
  Leftovers from versions before 1.1.3 (`*_temp_script.vpy`, `*.ffindex`,
  `*.lwi`, `*_part.*` beside the source, and the old system-temp index cache)
  are swept automatically.
