$ErrorActionPreference = "Stop"
$Global:InstallFailed = $false

# ==============================================================================
#  Auto-VHS-Deinterlacer Installer
# ==============================================================================
#  Author: Auto-VHS Team
#  Description: 
#    Automated installer for the Auto-VHS-Deinterlacer environment.
#    Sets up Python Virtual Environment, FFmpeg, and VapourSynth R73 Portable.
#    Handles complex dependency resolution including VapourSynth plugins (QTGMC stack).
# ==============================================================================

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  Auto-VHS-Deinterlacer Installer" -ForegroundColor Cyan
Write-Host "=================================================="
Write-Host ""

# ==============================================================================
# 1. Check for Python Availability
# ==============================================================================
try {
    $pythonVersion = python --version 2>&1
    Write-Host "[INFO] Found Python: $pythonVersion" -ForegroundColor Green
    if ($pythonVersion -notlike "*3.12*") {
        Write-Host "[WARNING] VapourSynth R73 works best with Python 3.12. You are using $pythonVersion." -ForegroundColor Yellow
        Write-Host "          If you encounter issues, please consider switching to Python 3.12." -ForegroundColor Yellow
    }
}
catch {
    Write-Host "[ERROR] Python is not installed or not in your PATH." -ForegroundColor Red
    Write-Host "Please install Python 3.10+ and try again."
    Pause
    Exit 1
}

# ==============================================================================
# 2. Check/Create Virtual Environment
# ==============================================================================
$venvPath = Join-Path $PSScriptRoot ".venv"
if (Test-Path $venvPath) {
    Write-Host "[.venv] Virtual environment already exists. Skipping creation." -ForegroundColor Yellow
}
else {
    Write-Host "[INFO] Creating Python Virtual Environment in .venv..." -ForegroundColor Cyan
    try {
        python -m venv $venvPath
    }
    catch {
        Write-Host "[ERROR] Failed to create virtual environment." -ForegroundColor Red
        Pause
        Exit 1
    }
}

# ==============================================================================
# 3. Upgrade pip
# ==============================================================================
Write-Host "[INFO] Upgrading pip..." -ForegroundColor Cyan
& "$venvPath\Scripts\python" -m pip install --upgrade pip

# ==============================================================================
# 4. Install Python Dependencies
# ==============================================================================
Write-Host "[INFO] Installing dependencies from requirements.txt..." -ForegroundColor Cyan
try {
    & "$venvPath\Scripts\python" -m pip install -r (Join-Path $PSScriptRoot "requirements.txt")
    
    # [FIX] We use a specific havsfunc r27 script for QTGMC compatibility.
    # We download it directly instead of using pip to avoid pulling unnecessary/failing dependencies.
    Write-Host "[INFO] Setting up havsfunc r27 script..." -ForegroundColor Cyan
    if (Test-Path "$venvPath\Lib\site-packages\havsfunc") { Remove-Item "$venvPath\Lib\site-packages\havsfunc" -Recurse -Force }
    Invoke-WebRequest -Uri "https://raw.githubusercontent.com/HomeOfVapourSynthEvolution/havsfunc/r27/havsfunc.py" -OutFile "$venvPath\Lib\site-packages\havsfunc.py"
    
    # [FIX] Patch havsfunc for VapourSynth R73 API compatibility
    # The r27 script uses vs.get_core() which is deprecated
    $patchScript = Join-Path $PSScriptRoot "patch_havsfunc.py"
    if (Test-Path $patchScript) {
        Write-Host "   -> Patching havsfunc for R73 compatibility..." -ForegroundColor Gray
        & "$venvPath\Scripts\python" $patchScript
    }
}
catch {
    Write-Host "[ERROR] Failed to install dependencies." -ForegroundColor Red
    $Global:InstallFailed = $true
}

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan

# ==============================================================================
# 5. Install Local FFmpeg (Self-Contained)
# ==============================================================================
$ffmpegDest = "$venvPath\Scripts\ffmpeg.exe"
if (-not (Test-Path $ffmpegDest)) {
    Write-Host "[INFO] FFmpeg not found in .venv. Downloading typical static build..." -ForegroundColor Cyan
    $ffmpegUrl = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
    $zipPath = Join-Path $PSScriptRoot "ffmpeg.zip"
    $extractPath = Join-Path $PSScriptRoot "ffmpeg_temp"

    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $ffmpegUrl -OutFile $zipPath -UseBasicParsing
        
        Write-Host "   -> Extracting..."
        Expand-Archive -Path $zipPath -DestinationPath $extractPath -Force
        
        $binPath = Get-ChildItem -Path $extractPath -Recurse -Filter "ffmpeg.exe" | Select-Object -First 1
        if ($binPath) {
            $sourceDir = $binPath.DirectoryName
            Copy-Item -Path "$sourceDir\ffmpeg.exe" -Destination "$venvPath\Scripts\" -Force
            Copy-Item -Path "$sourceDir\ffprobe.exe" -Destination "$venvPath\Scripts\" -Force
            Write-Host "   -> FFmpeg installed to .venv/Scripts/ (Self-Contained)" -ForegroundColor Green
        }
        else {
            throw "Could not find ffmpeg.exe in extracted archive."
        }
    }
    catch {
        Write-Host "[WARNING] Failed to auto-install FFmpeg: $_" -ForegroundColor Yellow
        Write-Host "The app will rely on system-wide FFmpeg instead."
    }
    finally {
        if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
        if (Test-Path $extractPath) { Remove-Item $extractPath -Recurse -Force }
    }
}
else {
    Write-Host "[INFO] Local FFmpeg already installed." -ForegroundColor Green
}

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan

# ==============================================================================
# 6. Install VapourSynth Portable (R73 / Self-Contained)
# ==============================================================================
# Note: R73 structure requires special handling for DLLs within wheels.
# It uses 'vs-plugins' and 'vs-coreplugins' directories.
# ==============================================================================
$vsDest = "$venvPath\vs\vspipe.exe"
if (-not (Test-Path $vsDest)) {
    Write-Host "[INFO] VapourSynth not found. Downloading Portable build..." -ForegroundColor Cyan
    $vsUrl = "https://github.com/vapoursynth/vapoursynth/releases/download/R73/VapourSynth64-Portable-R73.zip"
    
    $vsZip = Join-Path $PSScriptRoot "vs.zip"
    $vsExtractDir = "$venvPath\vs"

    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        
        # Download VS
        Write-Host "   -> Downloading VapourSynth R73..."
        Invoke-WebRequest -Uri $vsUrl -OutFile $vsZip -UseBasicParsing
        
        # [ROBUSTNESS] Folder Rotation Strategy
        # Rename existing folder instead of direct delete to bypass file locks from zombie processes.
        if (Test-Path $vsExtractDir) {
            Get-Process | Where-Object { $_.Modules.FileName -like "*$vsExtractDir*" -or $_.Name -eq "vspipe" } | Stop-Process -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 1
            $oldDir = "$vsExtractDir`_old_$(Get-Date -Format 'yyyyMMddHHmmss')"
            try { Rename-Item -Path $vsExtractDir -NewName (Split-Path $oldDir -Leaf) -ErrorAction SilentlyContinue } catch {}
            if (Test-Path $vsExtractDir) { 
                # If rename failed, try to delete contents as fallback
                try { Get-ChildItem -Path $vsExtractDir | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue } catch {}
            }
        }
        if (-not (Test-Path $vsExtractDir)) { New-Item -ItemType Directory -Path $vsExtractDir -Force | Out-Null }
        
        # Extract to a temp directory OUTSIDE of .venv/vs to prevent Move-Item nesting issues
        $tempExtractDir = Join-Path $PSScriptRoot "vs_extract_temp"
        if (Test-Path $tempExtractDir) { Remove-Item $tempExtractDir -Recurse -Force -ErrorAction SilentlyContinue }
        New-Item -ItemType Directory -Path $tempExtractDir -Force | Out-Null
        
        Write-Host "   -> Extracting VapourSynth archive..."
        Expand-Archive -Path $vsZip -DestinationPath $tempExtractDir -Force
        
        # Handle potential subfolder structure in zip
        $contentPath = $tempExtractDir
        $subFolder = Get-ChildItem -Path $tempExtractDir -Directory | Where-Object { Test-Path (Join-Path $_.FullName "vspipe.exe") } | Select-Object -First 1
        if ($subFolder) {
            $contentPath = $subFolder.FullName
            Write-Host "   -> Found subfolder structure: $($subFolder.Name)"
        }
        
        Write-Host "   -> Relocating files to vs root..."
        Get-ChildItem -Path $contentPath | ForEach-Object {
            try {
                Move-Item -Path $_.FullName -Destination $vsExtractDir -Force -ErrorAction Stop
            }
            catch {
                Write-Host "      [WARNING] Could not move $($_.Name): $($_.Exception.Message)" -ForegroundColor Yellow
            }
        }
        
        # Cleanup temp extraction folder
        if ($null -ne $tempExtractDir -and (Test-Path $tempExtractDir)) {
            Remove-Item $tempExtractDir -Recurse -Force -ErrorAction SilentlyContinue
        }
        # Cleanup rotated old dir if it exists
        if ($null -ne (Get-Variable -Name "oldDir" -ErrorAction SilentlyContinue)) {
            if (Test-Path $oldDir) {
                Remove-Item $oldDir -Recurse -Force -ErrorAction SilentlyContinue
            }
        }

        # [CLEANUP] DLL extraction logic removed as we use Python Pipe now.
        # The bundled vspipe.exe is ignored in favor of 'vspipe_native.py'.

        # Final check for DLL presence
        if (-not (Test-Path "$vsExtractDir\vapoursynth.dll")) {
            Write-Host "   -> Searching recursively for missing vapoursynth.dll..."
            $foundDll = Get-ChildItem -Path $vsExtractDir -Recurse -Filter "vapoursynth.dll" | Select-Object -First 1
            if ($foundDll) {
                Copy-Item $foundDll.FullName -Destination $vsExtractDir -Force
            }
        }

        # [PORTABLE MODE] Create portable.vs to enable portable mode
        if (-not (Test-Path "$vsExtractDir\portable.vs")) {
            New-Item -Path "$vsExtractDir\portable.vs" -ItemType File -Force | Out-Null
        }

        if (Test-Path "$vsExtractDir\vspipe.exe") {
            Write-Host "   -> VapourSynth installed to .venv/vs/ (Self-Contained)" -ForegroundColor Green
            
            # [PERFORMANCE FIX] Download Python 3.12 embeddable to enable vspipe.exe
            # The bundled VSScriptPython38.dll needs Python DLLs in the same directory
            Write-Host "   -> Downloading Python 3.12 embeddable for vspipe.exe..." -ForegroundColor Gray
            $pythonEmbedUrl = "https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip"
            $pythonEmbedZip = Join-Path $PSScriptRoot "python_embed.zip"
            try {
                Invoke-WebRequest -Uri $pythonEmbedUrl -OutFile $pythonEmbedZip -UseBasicParsing
                Expand-Archive -Path $pythonEmbedZip -DestinationPath $vsExtractDir -Force
                
                # [CRITICAL] Disable isolated mode by renaming the _pth file
                # This allows PYTHONHOME and PYTHONPATH to take effect
                $pthFile = Join-Path $vsExtractDir "python312._pth"
                if (Test-Path $pthFile) {
                    Rename-Item -Path $pthFile -NewName "python312._pth.disabled" -Force
                    Write-Host "      -> Disabled python312._pth isolation mode" -ForegroundColor Gray
                }
                Write-Host "      -> Python 3.12 embeddable installed for vspipe.exe" -ForegroundColor Green
            }
            catch {
                Write-Host "      [WARNING] Failed to download Python embeddable: $_" -ForegroundColor Yellow
            }
            finally {
                if (Test-Path $pythonEmbedZip) { Remove-Item $pythonEmbedZip -Force }
            }
        }
        else {
            throw "Extraction failed. vspipe.exe not found."
        }
    }
    catch {
        Write-Host "[WARNING] Failed to auto-install VapourSynth: $_" -ForegroundColor Yellow
        Write-Host "The app will rely on system-wide VapourSynth instead."
        $Global:InstallFailed = $true
    }
    finally {
        if (Test-Path $vsZip) { Remove-Item $vsZip -Force }
    }
}

# ==============================================================================
# 7. Install VapourSynth Plugins (QTGMC Stack)
# ==============================================================================
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "[INFO] Installing VapourSynth Plugins (QTGMC Stack)..." -ForegroundColor Cyan

$vsExtractDir = "$venvPath\vs"
$venvPython = "$venvPath\Scripts\python.exe"
$pluginsToInstall = "havsfunc lsmas mvtools nnedi3 nnedi3cl neo_fft3d removegrain fmtconv ffms2 eedi3 eedi3m"

# [R73 STANDARD] Use standard folder names as required by VapourSynth R73
$pluginsDirName = "vs-plugins"
$corePluginsDirName = "vs-coreplugins"

# 1. Install Bundled Wheel
# This ensures the Python environment matches the binary version
$wheelDir = Join-Path $vsExtractDir "wheel"
if (Test-Path $wheelDir) {
    if ($pythonVersion -like "*3.12*") {
        $wheel = Get-ChildItem -Path $wheelDir -Filter "vapoursynth-*-cp312-*.whl" | Select-Object -First 1
        if ($wheel) {
            Write-Host "   -> Installing bundled VapourSynth wheel into venv..." -ForegroundColor Gray
            & $venvPython -m pip install $wheel.FullName --force-reinstall | Out-Null
        }
    }
    else {
        Write-Host "   -> Skipping bundled wheel (version mismatch: requires Python 3.12)." -ForegroundColor Yellow
    }
}

# 2. Sync Portable Markers (Fix for "Autoloading Failed")
# By copying portable.vs and core plugins to site-packages, we ensure the Python module
# initializes correctly even when mixed with system paths.
try {
    $sitePkgs = & $venvPython -c "import site; print(site.getsitepackages()[0])"
    if (Test-Path $sitePkgs) {
        Write-Host "   -> Syncing portable markers to venv site-packages..." -ForegroundColor Gray
        Copy-Item (Join-Path $vsExtractDir "portable.vs") -Destination $sitePkgs -Force -ErrorAction SilentlyContinue
        
        $srcCore = Join-Path $vsExtractDir $corePluginsDirName
        if (Test-Path $srcCore) {
            $destCore = Join-Path $sitePkgs $corePluginsDirName
            if (-not (Test-Path $destCore)) { New-Item -ItemType Directory -Path $destCore -Force | Out-Null }
            Copy-Item "$srcCore\*" -Destination $destCore -Force -Recurse -ErrorAction SilentlyContinue
        }
    }
}
catch {
    Write-Host "[WARNING] Failed to sync portable markers: $_" -ForegroundColor Yellow
}

# Identify plugin runner (prefer portable python if available)
$pythonExe = $null
$possiblePythonPaths = @(
    "$vsExtractDir\python.exe",
    "$vsExtractDir\Scripts\python.exe",
    "$vsExtractDir\sdk\python.exe"
)
foreach ($path in $possiblePythonPaths) {
    if (Test-Path $path) { $pythonExe = $path; break }
}

$vsRepoScript = $null
$possibleVsRepoPaths = @(
    "$vsExtractDir\vsrepo.py",
    "$vsExtractDir\Scripts\vsrepo.py",
    "$vsExtractDir\sdk\vsrepo.py"
)
foreach ($path in $possibleVsRepoPaths) {
    if (Test-Path $path) { $vsRepoScript = $path; break }
}

# Fallback searches
if (-not $pythonExe) {
    $foundPython = Get-ChildItem -Path $vsExtractDir -Recurse -Filter "python.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($foundPython) { $pythonExe = $foundPython.FullName }
}
if (-not $vsRepoScript) {
    $foundVsRepo = Get-ChildItem -Path $vsExtractDir -Recurse -Filter "vsrepo.py" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($foundVsRepo) { $vsRepoScript = $foundVsRepo.FullName }
}

# Determine Runner
if ($pythonExe -and (Test-Path $pythonExe)) {
    Write-Host "   -> Found portable Python: $pythonExe" -ForegroundColor Gray
    $runner = $pythonExe
}
else {
    Write-Host "[WARNING] Portable Python not found. Using venv Python for plugin install..." -ForegroundColor Yellow
    $runner = $venvPython
}

# Run vsrepo to install plugins
if ($vsRepoScript -and (Test-Path $vsRepoScript)) {
    try {
        $originalLocation = Get-Location
        Set-Location -Path $vsExtractDir
        
        # Ensure directories exist
        foreach ($dir in @($pluginsDirName, $corePluginsDirName)) {
            if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
        }

        # [ISOLATION] Isolate vsrepo from user's system plugins
        $fakeAppData = Join-Path $vsExtractDir "fake_appdata"
        if (-not (Test-Path $fakeAppData)) { New-Item -ItemType Directory -Path $fakeAppData -Force | Out-Null }
        
        $oldAppData = $env:APPDATA
        $oldLocalAppData = $env:LOCALAPPDATA
        $env:APPDATA = $fakeAppData
        $env:LOCALAPPDATA = $fakeAppData
        $env:VAPOURSYNTH_PLUGINS = Join-Path $vsExtractDir $pluginsDirName

        try {
            Write-Host "   -> Updating vsrepo definitions..."
            & $runner $vsRepoScript -p update

            Write-Host "   -> Running vsrepo install for: $pluginsToInstall"
            $pluginArgs = $pluginsToInstall -split " "
            
            # Use -ErrorAction SilentlyContinue and manual check to avoid failing on optional plugins
            & $runner $vsRepoScript -p install $pluginArgs 2>&1 | Write-Host -ForegroundColor Gray
            
            if ($LASTEXITCODE -eq 0) {
                Write-Host "   -> Plugins installed successfully." -ForegroundColor Green
            }
            else {
                Write-Host "   -> [NOTICE] Some plugins failed to install. This is often normal if they are already present or optional." -ForegroundColor Yellow
                # Don't set Global:InstallFailed = $true here unless it's a critical failure
            }
            
            # Install vsutil (often needed helper)
            & $runner -m pip install vsutil | Out-Null
        }
        finally {
            $env:APPDATA = $oldAppData
            $env:LOCALAPPDATA = $oldLocalAppData
            Set-Location -Path $originalLocation
        }
    }
    catch {
        Write-Host "[ERROR] Failed to install plugins: $_" -ForegroundColor Red
        $Global:InstallFailed = $true
    }
}
else {
    Write-Host "[ERROR] vsrepo.py script not found. Cannot install plugins." -ForegroundColor Red
    $Global:InstallFailed = $true
}

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan

# ==============================================================================
# 8. Generate Launcher (start.bat)
# ==============================================================================
Write-Host "Generating launcher: start.bat..." -ForegroundColor Cyan
$batchContent = @"
@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found.
    echo Please run 'install.ps1' - Right-click and Run with PowerShell - first.
    pause
    exit /b 1
)

echo Starting Auto-VHS-Deinterlacer...
REM %* passes all arguments (dragged files) to the script
".venv\Scripts\python.exe" auto_deinterlancer.py %*

if %errorlevel% neq 0 (
    echo.
    echo [APP ERROR] The application crashed or exited with an error.
    pause
) else (
    echo.
    echo Application finished.
    pause
)
"@
Set-Content -Path "start.bat" -Value $batchContent

if ($Global:InstallFailed) {
    Write-Host "`n==================================================" -ForegroundColor Red
    Write-Host "[ERROR] Installation completed with errors." -ForegroundColor Red
    Write-Host "Some components may not be working correctly." -ForegroundColor Red
    Write-Host "Check the logs above for red [ERROR] and orange [WARNING] messages." -ForegroundColor Yellow
    Write-Host "=================================================="
}
else {
    Write-Host "`nInstallation Complete!" -ForegroundColor Green
    Write-Host "You can now Run the application by:"
    Write-Host "1. Double-clicking 'start.bat'"
    Write-Host "2. Dragging video files onto 'start.bat'" -ForegroundColor Yellow
    Write-Host "Done."
}

Write-Host ""
Pause

if ($Global:InstallFailed) { Exit 1 }
Exit 0
