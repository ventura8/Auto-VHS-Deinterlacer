---
name: test-runner
description: Execute unit, integration, and native fallback pytest suites with coverage measurement and mocking boundaries.
---

# Test Runner Skill

Use this skill to execute unit tests, integration tests, and native fallback tests independently while measuring code coverage and adhering to repository boundary invariants.

## Testing Philosophy & Mocking Boundaries

1. **Windows/Linux Cross-Platform Compatibility**: Mocks and tests must execute seamlessly across both Windows (where actual VapourSynth DLLs/pip wheels may live) and Linux (such as GitHub Actions Ubuntu runners).
1. **External Boundaries Only**: Mock only external subprocesses or system resources:
   - External CLI commands (`ffmpeg`, `ffprobe`, `vspipe.exe`).
   - Hardware detection APIs (CUDA / PyTorch GPU memory probing) via `AUTO_VHS_SKIP_HW_DETECT=1`.
   - File system I/O when simulating error cases.
1. **Never Mock Owned Project Code**: Do not mock internal business logic or cross-call functions from `auto_deinterlancer.py`, `modules.core.*`, or `modules.runtime.*`. Execute real module code.
1. **Coverage Invariant**: Maintain ≥90% line coverage across all product modules (`auto_deinterlancer.py`, `modules/core/*.py`, `modules/runtime/*.py`) with branch coverage tracking enabled.

## Running Test Suites

### 1. Focused / Fast Test Runs

When iterating on code changes, execute focused slices without full coverage instrumentation first:

```powershell
# Run all tests without coverage overrides (fast)
.\.VENV\Scripts\python.exe -m pytest -o addopts=

# Targeted test slice (with hardware isolation)
$prevSkipHw = $env:AUTO_VHS_SKIP_HW_DETECT
$env:AUTO_VHS_SKIP_HW_DETECT = "1"
try {
    .\.VENV\Scripts\python.exe -m pytest -o addopts= tests/unit/
    if ($LASTEXITCODE -ne 0) { throw "Unit tests failed with exit code $LASTEXITCODE" }
    .\.VENV\Scripts\python.exe -m pytest -o addopts= tests/integration/
    if ($LASTEXITCODE -ne 0) { throw "Integration tests failed with exit code $LASTEXITCODE" }
    .\.VENV\Scripts\python.exe -m pytest -o addopts= tests/native/
    if ($LASTEXITCODE -ne 0) { throw "Native tests failed with exit code $LASTEXITCODE" }
}
finally {
    if ($null -ne $prevSkipHw) { $env:AUTO_VHS_SKIP_HW_DETECT = $prevSkipHw } else { Remove-Item Env:AUTO_VHS_SKIP_HW_DETECT -ErrorAction SilentlyContinue }
}

# Single test file
$prevSkipHw = $env:AUTO_VHS_SKIP_HW_DETECT
$env:AUTO_VHS_SKIP_HW_DETECT = "1"
try {
    .\.VENV\Scripts\python.exe -m pytest -o addopts= tests/unit/test_config_validation.py
}
finally {
    if ($null -ne $prevSkipHw) { $env:AUTO_VHS_SKIP_HW_DETECT = $prevSkipHw } else { Remove-Item Env:AUTO_VHS_SKIP_HW_DETECT -ErrorAction SilentlyContinue }
}
```

### 2. Full Suite with Coverage & XML Export

To measure coverage accurately and generate `assets/coverage.xml`:

```powershell
$prevSkipHw = $env:AUTO_VHS_SKIP_HW_DETECT
$env:AUTO_VHS_SKIP_HW_DETECT = "1"
try {
    .\.VENV\Scripts\python.exe -m pytest --cov=modules --cov=auto_deinterlancer --cov-branch --cov-report=xml:assets/coverage.xml --cov-report=term --cov-fail-under=90 tests/
    if ($LASTEXITCODE -ne 0) {
        throw "Pytest failed with exit code $LASTEXITCODE"
    }
}
finally {
    if ($null -ne $prevSkipHw) { $env:AUTO_VHS_SKIP_HW_DETECT = $prevSkipHw } else { Remove-Item Env:AUTO_VHS_SKIP_HW_DETECT -ErrorAction SilentlyContinue }
}
```

### 3. Verify Coverage Gates

```powershell
# Enforce ≥90% on every single source file
.\.VENV\Scripts\python.exe -m poetry run python .github/scripts/enforce_per_file_coverage.py assets/coverage.xml 90
```
