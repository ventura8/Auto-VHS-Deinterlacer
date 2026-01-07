# UI Standards

To maintain a "Studio Reference" aesthetic, the CLI must follow these rules:

## 1. Startup Sequence
- **Progress Bars**: Use ASCII-based progress bars (`█`) for the initialization sequence.
  - "Initializing Core Systems..."
  - "Scanning Hardware..."
  - "Optimizing for [GPU]..."
- **Delays**: Artificial but short delays (`time.sleep(0.2)`) provide a sense of "heaviness" and thorough checking.

## 2. Banner
- Must display strictly formatted system info:
    ```
    ============================================================
       AUTO-VHS-DEINTERLACER - v1.0.0
    ============================================================
     CPU: AMD Ryzen 9 9950X3D 16-Core Processor
     GPU: NVIDIA GeForce RTX 5090
     Profile: ARCHIVAL GRADE (QTGMC)
    ------------------------------------------------------------
    ```

## 3. Input Handling
- **Drag & Drop**: Primary method.
- **Interactive**: Fallback if no args provided.
- **Batch**: If a folder is dropped, process all valid video extensions.

## 4. Rendering Progress
- **Format**: Unified bar with real-time stats.
    ```
    [██████████░░░░░░░░░░░░░░░] 40% | 00:04:15 | 2.1x | ETA: 00:01:05 | Rendering...
    ```
- **Elements**:
  - `[...|...]`: 30-char visual bar.
  - `40%`: Percentage complete.
  - `00:04:15`: Current timestamp in video.
  - `2.1x`: Rendering speed (frames/sec relative to playback).
  - `ETA`: Estimated time remaining (Formatted `HH:MM:SS` or `MM:SS`).
  - Label: Current activity (e.g., "Rendering...", "Muxing...").
