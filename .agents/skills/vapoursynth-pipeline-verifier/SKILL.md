---
name: vapoursynth-pipeline-verifier
description: Inspect and verify VapourSynth deinterlacing script generation, QTGMC presets, havsfunc compatibility patching, and hardware acceleration detection.
---

# VapourSynth Pipeline Verifier Skill

Use this skill to verify VapourSynth script (.vpy) synthesis, QTGMC deinterlacing presets, audio-video synchronization logic, and native Python fallback execution in Auto-VHS-Deinterlacer.

## Core Architectural Invariants

1. **QTGMC & Havsfunc Compatibility**:
   - `modules/core/patch_havsfunc.py` performs setup-time AST/regex compatibility patches on bundled `havsfunc.py` for Python 3.12 compatibility.
   - Never remove the patch mechanism without verifying all native tests pass.
1. **Dual-Mode VapourSynth Execution**:
   - Primary: `modules/runtime/vspipe.py` invokes external `vspipe.exe` streaming raw YUV to FFmpeg.
   - Fallback: `modules/runtime/vspipe_native.py` runs embedded VapourSynth Python bindings if `vspipe.exe` is absent or fails.
1. **Hardware Acceleration Tiers**:
   - `modules/core/config.py` evaluates system RAM, CPU cores, and NVIDIA CUDA GPU VRAM to dynamically configure optimal memory allocation, thread count, and hardware decoding.

## Verification Workflows

### 1. Test Havsfunc Compatibility Patching

```powershell
.\.VENV\Scripts\python.exe -m pytest -o addopts= tests/native/test_patch_havsfunc.py
```

### 2. Test VSPipe & Native Fallback Handlers

```powershell
.\.VENV\Scripts\python.exe -m pytest -o addopts= tests/native/test_native_modules.py
```

### 3. Test Pipeline Branching & Resilience

```powershell
.\.VENV\Scripts\python.exe -m pytest -o addopts= tests/integration/test_pipeline_branching.py tests/integration/test_pipeline_resilience.py
```

### 4. Inspect Synthesized VapourSynth Script

Verify generated `.vpy` scripts against source video specs:

- Field order parity (TFF vs BFF).
- Correct source filter loader (`lsmas.LWLibavSource`, `ffms2.Source`, or `core.ffms2.Source`).
- Proper color matrix and pixel format preservation (YUV420P / YUV422P).
