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

### Entry (<24GB RAM)
- **Threshold**: Laptops or older desktops.
- **Behavior**: Allocates **25% system RAM** to cache.
- **Benefit**: Stable processing without OS-level memory pressure.

## GPU Acceleration
The script automatically detects NVIDIA GPUs via `nvidia-smi`:
- **OpenCL**: If found, enables `NNEDI3CL` within QTGMC for a massive speedup (approx 4x-10x) vs. CPU-only NNEDI3.
- **NVENC**: If the encoder is set to `av1`, it uses `av1_nvenc` for near-instant encoding.

## CPU Scaling
- **Conncurency**: Automatically scales threads to match your core count (e.g., 32 threads for FFmpeg & VapourSynth on a 16-core CPU).
- **ProRes**: Uses `prores_ks` (10-bit) which is highly optimized for multi-core processors.
- **SVT-AV1**: Uses all available threads if hardware AV1 encoding is not available.
