# Hardware Optimization

The system implements specific profiles to maximize hardware usage.

## Hardware Detection Logic

The `detect_hardware_settings()` function scans the system on startup:

```python
settings = {
    "cpu_threads": os.cpu_count() or 16,
    "ram_cache_mb": 4000,  # Default
    "use_gpu_opencl": True,  # Optimistic Default
}
```

## Profiles

### High-Performance (>48GB RAM)

- **Threshold**: Systems like Ryzen 9950X3D with 64GB+ RAM.
- **Behavior**: Allocates **50% system RAM** (up to 48GB) to VapourSynth cache.
- **Benefit**: Smooth 10-bit processing and maximum temporal analysis speed.

### Standard (24GB - 48GB RAM)

- **Threshold**: Typical workstations (32GB RAM).
- **Behavior**: Allocates **35% system RAM** to cache.
- **Benefit**: Prevents disk swapping during complex QTGMC calls.

### Entry (\<24GB RAM)

- **Threshold**: Laptops or older desktops.
- **Behavior**: Allocates **25% system RAM** to cache.
- **Benefit**: Stable processing without OS-level memory pressure.

## GPU Acceleration

The script automatically detects NVIDIA GPUs via `nvidia-smi`:

- **OpenCL**: QTGMC's default `NNEDI3` interpolation mode needs `NNEDI3CL`.
  `EdiMode: eedi3` and `EdiMode: eedi3+nnedi3` additionally require `EEDI3CL`.
  A one-frame isolated render probe also rejects plugins that crash or fail at
  runtime. If the selected path is unavailable or unstable, QTGMC safely uses
  its CPU implementation.
- **Legacy plugin notices**: The startup probe filters repeated VapourSynth API3
  deprecation notices from the user-facing console. Processing errors and other
  VapourSynth warnings remain visible.
- **NVENC**: With `encoder: av1`, the app uses `av1_nvenc` only after a one-frame
  FFmpeg probe succeeds. The probe uses a valid 256×256 frame, avoiding false
  negatives from NVENC's minimum frame-size requirement. GPU detection alone is not sufficient: the GPU, its
  driver, and the FFmpeg NVENC build must all support AV1 encoding. Otherwise it
  uses CPU-based `libsvtav1`. NVIDIA Ampere RTX 30-series GPUs, including the
  RTX 3080 Laptop GPU, do not provide AV1 NVENC encoding.
- **NVENC level**: `av1_nvenc` runs with `-level 5.1`. Left unpinned it writes
  `seq_level_idx` 23 (level 7.3) even for SD sources; the AV1 specification does
  not define the 7.x levels, so libaom rejects those files while dav1d plays them.
  5.1 covers everything up to 4K60.
- **NVENC in the installers**: after installing FFmpeg, both installers encode
  one real `av1_nvenc` frame and report whether AV1 output will use the GPU, and
  if not, why. On Linux, `install.sh` also installs the NVENC userspace library
  (`libnvidia-encode.so.1`) when an NVIDIA driver is present without it, because
  some distributions package it separately (Ubuntu's headless and server driver
  flavours omit it): `libnvidia-encode-<branch>` on Debian/Ubuntu,
  `xorg-x11-drv-nvidia-cuda-libs` on Fedora, `nvidia-utils` on Arch. On Windows
  the display driver always ships the NVENC runtime, so nothing is installed.
  The kernel driver itself is never installed or upgraded by the installers.
  Set `AVD_SKIP_NVENC=1` to skip the step.
- **Driver versus bundled FFmpeg**: the bundled FFmpeg is built against a recent
  NVENC SDK, and a driver that predates it blocks every NVENC encoder, not only
  AV1. The installer reports the minimum driver FFmpeg itself names (for example
  "needs 610.00 or newer" for FFmpeg 9.0.x). Updating the driver cannot add AV1
  NVENC to a GPU that lacks it: on an RTX 30-series card it only enables NVENC
  codecs this pipeline does not use.

## CPU Scaling

- **Conncurency**: Automatically scales threads to match your core count (e.g., 32 threads for FFmpeg & VapourSynth on a 16-core CPU).
- **ProRes**: Uses `prores_ks` (10-bit) which is highly optimized for multi-core processors.
- **SVT-AV1**: Uses all available threads if hardware AV1 encoding is not available.
