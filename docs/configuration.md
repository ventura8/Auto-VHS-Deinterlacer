# Configuration

The project uses `config.yaml` as the central source of truth.

## Default `config.yaml`
```yaml
# Input/Output paths can be absolute or relative
input_file: "C:\\Input.mp4"
output_file: "C:\\Output.mp4"

# Modes: "QTGMC" (Default)
deinterlace_mode: "QTGMC"

# Encoders:
# - "prores" (ProRes 422 HQ)
# - "av1" (SVT-AV1 10-bit)
encoder: "prores"

# QTGMC Restoration Settings
# Allows fine-tuning of the "Archival Restoration" deinterlacer.
qtgmc_settings:
  Preset: "Very Slow" # Speed/Quality balance ("Placebo" = Diminishing returns)
  SourceMatch: 3      # Match source pixels (Fidelity)
  Lossless: 2         # Discard new pixels if they match source
  EZDenoise: 1.5      # 0.0-5.0: Noise reduction strength
  NoiseProcess: 2     # Stabilize noise
  Sharpness: 0.8      # 0.0-1.5: Detail enhancement

# Performance
# "auto" detects hardware.
# "manual" uses manual_settings block.
performance_profile: "auto"

manual_settings:
  cpu_threads: 32

# Sync Logic
auto_drift_correction: true  # Enabled by default
audio_sync_offset: 0.0       # Manual delay in seconds
```

## Logic
- **Loader**: `load_config()` uses PyYAML to parse the file safely.
- **Fallbacks**: If keys are missing, the script defaults to hardcoded safe values (e.g., QTGMC, 16 threads).
