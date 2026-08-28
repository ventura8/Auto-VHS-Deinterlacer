---
name: installer-tester
description: Validate interactive PowerShell installation, environment setup, and runtime launcher scripts.
---

# Installer Tester Skill

Use this skill to inspect, validate, and test `install.ps1` and launcher scripts (`start.bat`) for Auto-VHS-Deinterlacer on Windows.

## Overview & Components

The installer orchestrates:

1. **Python Interpreter Check**: Ensures Python 3.12 64-bit is installed and available.
1. **Virtualenv Creation**: Provisions `.VENV` using `python -m venv .VENV`.
1. **Pip & Poetry Bootstrapping**: Installs pinned `poetry==2.4.1` into `.VENV`.
1. **Downloaded Asset Verification & Retries**: Downloads `7-Zip`, `FFmpeg`, and `havsfunc.py` with strict SHA-256 integrity verification, automatic deletion of corrupt files, and retry logic.
1. **VapourSynth Pip-Backed Runtime**: Provisions pip wheels and VapourSynth plugins into `.VENV\Lib\site-packages\vapoursynth`.
1. **Havsfunc Compatibility Patching**: Runs `modules.core.patch_havsfunc` to ensure QTGMC and related VHS restoration filters operate seamlessly on Python 3.12 without deprecation breakage.
1. **Launcher Script Verification**: Ensures `start.bat` correctly references `.VENV\Scripts\python.exe auto_deinterlancer.py`.

## Testing the Installer Flow

### 1. Test Syntax and PSScriptAnalyzer

```powershell
.\.github\scripts\run_powershell_lint.ps1 -RepoRoot (Get-Location)
```

### 2. Test Havsfunc Compatibility Patching

Execute the dedicated native test suite to verify that havsfunc patching logic succeeds and handles edge cases:

```powershell
.\.VENV\Scripts\python.exe -m pytest -o addopts= tests/native/test_patch_havsfunc.py
```

### 3. Dry-Run / Verification of install.ps1 and Environment Components

Verify the structure and non-interactive steps in `install.ps1`:

```powershell
powershell -ExecutionPolicy Bypass -Command {
    Get-Command .\install.ps1
    # Check syntax parsing
    [System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path .\install.ps1), [ref]$null, [ref]$errors)
    if ($errors) { throw $errors }
}
```

### 4. Non-Destructive Environment & Component Assertions

Verify all provisioned components and launcher targets:

```powershell
# 1. Python 3.12 64-bit interpreter
& .\.VENV\Scripts\python.exe -c "import sys; assert sys.version_info[:2] == (3, 12) and sys.maxsize > 2**32, 'Python 3.12 64-bit required'"
if ($LASTEXITCODE -ne 0) { throw "Python 3.12 64-bit check failed with exit code $LASTEXITCODE" }

# 2. Pinned Poetry version
$poetryVerOutput = (& .\.VENV\Scripts\python.exe -m poetry --version)
if ($LASTEXITCODE -ne 0 -or $poetryVerOutput -notmatch '2\.4\.1') {
    throw "Poetry version check failed! Expected 2.4.1, got: $poetryVerOutput"
}

# 3. VapourSynth runtime & plugins
& .\.VENV\Scripts\python.exe -c "import vapoursynth as vs; core = vs.core; assert core is not None"
if ($LASTEXITCODE -ne 0) { throw "VapourSynth check failed with exit code $LASTEXITCODE" }

# 4. Havsfunc import and patch integrity
& .\.VENV\Scripts\python.exe -c "import havsfunc; assert havsfunc is not None"
if ($LASTEXITCODE -ne 0) { throw "Havsfunc check failed with exit code $LASTEXITCODE" }

# 5. Launcher script target verification (if start.bat exists)
if (Test-Path "start.bat") {
    $batContent = Get-Content "start.bat" -Raw
    if ($batContent -notmatch '"\.venv\\Scripts\\python\.exe"\s+auto_deinterlancer\.py') {
        throw "start.bat does not target auto_deinterlancer.py correctly"
    }
}
```
