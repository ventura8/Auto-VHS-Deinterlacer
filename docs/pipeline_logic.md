# Pipeline Logic

The `auto_deinterlancer.py` script executes a strictly ordered 4-stage pipeline for each video file.

## Step 1: Hardware Detection (Pre-Flight)
Before processing begins, the script:
1.  **Checks CPU Cores**: Uses `os.cpu_count()` to determine optimal thread count.
2.  **Checks RAM**: Uses `GlobalMemoryStatusEx` to detect system RAM.
    -   **High-Performance Profile**: If RAM > 48GB, allocates 50% for cache.
    -   **Mid/Standard Profile**: If RAM > 24GB, allocates 35% for cache.
3.  **Checks GPU**: Scans for `nvidia-smi` to enable OpenCL/NVENC acceleration.

## Step 2: Single-Pass Analysis & Processing

### 2a. Script & Analysis
1.  **Script Generation**: A VapourSynth (`.vpy`) script is created (dependency-injected with local `.venv`).
2.  **Pre-Flight Check**: The script is dry-run (`vspipe --info`) to extract exact Frame Count and FPS.
    -   **Drift Calculation**: Compares Source Audio Duration vs. Script Video Duration.
    -   **Correction Logic**:
        -   Drift < 10ms: Ignored.
        -   Drift > 1.5%: Ignored (safety cap).
        -   Valid Drift: Calculated as `speed_factor` for real-time correction.

### 2b. Single-Pass Execution
The pipeline executes a **single** consolidated command:
`VSPipe (Y4M) | FFmpeg (Input 0: Pipe, Input 1: Source Audio)`

-   **Video Flow**: Deinterlaced frames are piped directly to FFmpeg.
-   **Audio Flow**: Source audio is read, and `atempo` filters are applied on-the-fly if drift correction is needed.
-   **Encoding**:
    -   **ProRes**: Encodes to ProRes 422 HQ (10-bit).
    -   **AV1**: Transcodes to SVT-AV1 or NVENC AV1.

## Step 3: Robustness & Cleanup
The pipeline is designed to be "Power Loss Tolerant".
- **Unique Naming**: Temporary scripts and intermediate files use unique identifiers based on the input filename.
- **Resume Capability**: Checks if the final output exists to avoid re-processing.
- **Auto-Cleanup**: Automatically removes temporary scripts and index files (`.ffindex`, `.lwi`) upon success.
