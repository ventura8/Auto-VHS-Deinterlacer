param(
    # Suppress the interactive "press any key" prompts so unattended runs
    # (dockurr/windows OEM setup, CI) can never block on input.
    [switch]$NoPause
)

$ErrorActionPreference = "Stop"
$InstallFailed = $false
$script:PauseEnabled = -not $NoPause

function Invoke-Pause {
    if ($script:PauseEnabled) {
        Pause
    }
}

function Initialize-VsRepo7Zip {
    param(
        [Parameter(Mandatory = $true)]
        [string]$VenvPath
    )

    $vsRepoPackageDir = Join-Path $VenvPath "Lib\site-packages\vsrepo"
    if (-not (Test-Path $vsRepoPackageDir)) {
        return $false
    }

    $local7ZipPath = Join-Path $vsRepoPackageDir "7z.exe"
    if (Test-Path $local7ZipPath) {
        return $true
    }

    $path7ZipCommand = Get-Command "7z.exe" -ErrorAction SilentlyContinue
    if ($path7ZipCommand -and (Test-Path $path7ZipCommand.Source)) {
        Copy-Item -Path $path7ZipCommand.Source -Destination $local7ZipPath -Force
        Write-Output "   -> Reusing system 7z.exe for vsrepo extraction."
        return $true
    }

    $sevenZipUrl = "https://www.7-zip.org/a/7za920.zip"
    $sevenZipExpectedSha256 = "2A3AFE19C180F8373FA02FF00254D5394FEC0349F5804E0AD2F6067854FF28AC"
    $tempRoot = Join-Path $env:TEMP ("auto-vhs-7zip-" + [guid]::NewGuid().ToString("N"))
    $tempZipPath = Join-Path $tempRoot "7za920.zip"
    $tempExtractPath = Join-Path $tempRoot "extract"

    try {
        Write-Output "   -> 7z.exe not found. Bootstrapping standalone 7-Zip..."
        New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
        
        $sevenZipSuccess = $false
        for ($attempt = 1; $attempt -le 3; $attempt++) {
            if (Test-Path $tempZipPath) { Remove-Item -Path $tempZipPath -Force -ErrorAction SilentlyContinue }
            try {
                Invoke-WebRequest -Uri $sevenZipUrl -OutFile $tempZipPath

                $downloadedHash = (Get-FileHash -Path $tempZipPath -Algorithm SHA256).Hash
                if ($downloadedHash -eq $sevenZipExpectedSha256) {
                    $sevenZipSuccess = $true
                    break
                }
                else {
                    Write-Output "   -> [WARNING] 7-Zip SHA256 integrity check failed on attempt $attempt! Expected: $sevenZipExpectedSha256, got: $downloadedHash"
                    Remove-Item -Path $tempZipPath -Force -ErrorAction SilentlyContinue
                    Write-Output "      Deleted corrupt archive; retrying download..."
                }
            }
            catch {
                $err = $_.Exception.Message
                Write-Output "   -> [WARNING] 7-Zip download failed on attempt ${attempt}: $err"
                if (Test-Path $tempZipPath) { Remove-Item -Path $tempZipPath -Force -ErrorAction SilentlyContinue }
                if ($attempt -lt 3) {
                    Write-Output "      Retrying download..."
                }
            }
        }

        if (-not $sevenZipSuccess) {
            throw "7-Zip SHA256 integrity check failed after multiple attempts."
        }

        Expand-Archive -Path $tempZipPath -DestinationPath $tempExtractPath -Force

        $standalone7Zip = Join-Path $tempExtractPath "7za.exe"
        if (-not (Test-Path $standalone7Zip)) {
            throw "7za.exe not found in downloaded archive."
        }

        Copy-Item -Path $standalone7Zip -Destination $local7ZipPath -Force
        Write-Output "   -> Bootstrapped 7z.exe for vsrepo extraction."
        return $true
    }
    catch {
        Write-Output "   -> [NOTICE] Could not bootstrap 7-Zip automatically: $_"
        return $false
    }
    finally {
        if (Test-Path $tempRoot) {
            Remove-Item -Path $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

# ==============================================================================
#  Auto-VHS-Deinterlacer Installer
# ==============================================================================
#  Author: Auto-VHS Team
#  Description:
#    Automated installer for the Auto-VHS-Deinterlacer environment.
#    Sets up Python Virtual Environment, FFmpeg, and VapourSynth runtime tooling.
#    Handles complex dependency resolution including VapourSynth plugins (QTGMC stack).
# ==============================================================================

Write-Output "=================================================="
Write-Output "  Auto-VHS-Deinterlacer Installer"
Write-Output "=================================================="
Write-Output ""

# ==============================================================================
# 1. Check for Python Availability
# ==============================================================================
try {
    $isWindowsArm64 = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture -eq [System.Runtime.InteropServices.Architecture]::Arm64
    $requiredPythonMinor = "3.12"
    $pythonAbiTag = "cp312"
    Write-Output "[INFO] Target runtime: Python $requiredPythonMinor ($([System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture); ARM64=$isWindowsArm64)"

    $pythonLauncherVersion = $null
    $pythonCommand = $null
    try {
        $pythonLauncherVersion = py "-$requiredPythonMinor" --version 2>&1
    }
    catch {
        $pythonLauncherVersion = $null
    }

    if ($LASTEXITCODE -eq 0 -and $pythonLauncherVersion) {
        $pythonVersion = $pythonLauncherVersion
        $pythonCommand = @("py", "-$requiredPythonMinor")
    }
    else {
        $pythonVersion = python --version 2>&1
        $pythonCommand = @("python")

        if (-not ([regex]::IsMatch($pythonVersion, "Python\s+$([regex]::Escape($requiredPythonMinor))\.\d+"))) {
            $pythonCandidate = Join-Path $env:LocalAppData "Programs\Python\Python$($requiredPythonMinor.Replace('.', ''))\python.exe"
            if (Test-Path $pythonCandidate) {
                $pythonVersion = & $pythonCandidate --version 2>&1
                if ([regex]::IsMatch($pythonVersion, "Python\s+$([regex]::Escape($requiredPythonMinor))\.\d+")) {
                    $pythonCommand = @($pythonCandidate)
                }
            }
        }
    }

    Write-Output "[INFO] Found Python: $pythonVersion"
    $pythonVersionMatch = [regex]::Match($pythonVersion, "Python\s+($([regex]::Escape($requiredPythonMinor))\.\d+)")
    if (-not $pythonVersionMatch.Success) {
        Write-Output "[ERROR] Python $requiredPythonMinor is required. Found: $pythonVersion"
        Write-Output "Install Python $requiredPythonMinor, then rerun install.ps1."
        Write-Output "Tip: If Python $requiredPythonMinor is installed, run this script with: py -$requiredPythonMinor .\install.ps1"
        Invoke-Pause
        Exit 1
    }
}
catch {
    Write-Output "[ERROR] Python is not installed or not in your PATH."
    Write-Output "Please install the required Python runtime and try again."
    Invoke-Pause
    Exit 1
}

# ==============================================================================
# 2. Check/Create Virtual Environment
# ==============================================================================
$venvPath = Join-Path $PSScriptRoot ".venv"
if (Test-Path $venvPath) {
    $existingVenvPython = Join-Path $venvPath "Scripts\python.exe"
    $existingVenvVersion = $null
    if (Test-Path $existingVenvPython) {
        try {
            $existingVenvVersion = & $existingVenvPython --version 2>&1
        }
        catch {
            $existingVenvVersion = $null
        }
    }

    if ($existingVenvVersion -and $existingVenvVersion -match "Python\s+$([regex]::Escape($requiredPythonMinor))\.") {
        Write-Output "[.venv] Python $requiredPythonMinor virtual environment already exists. Skipping creation."
    }
    else {
        Write-Output "[INFO] Existing .venv is not Python $requiredPythonMinor. Recreating virtual environment..."
        try {
            Remove-Item -Path $venvPath -Recurse -Force
            if ($pythonCommand.Count -eq 2) {
                & $pythonCommand[0] $pythonCommand[1] -m venv $venvPath
            }
            else {
                & $pythonCommand[0] -m venv $venvPath
            }
        }
        catch {
            Write-Output "[ERROR] Failed to recreate virtual environment."
            Invoke-Pause
            Exit 1
        }
    }
}
else {
    Write-Output "[INFO] Creating Python Virtual Environment in .venv..."
    try {
        if ($pythonCommand.Count -eq 2) {
            & $pythonCommand[0] $pythonCommand[1] -m venv $venvPath
        }
        else {
            & $pythonCommand[0] -m venv $venvPath
        }
    }
    catch {
        Write-Output "[ERROR] Failed to create virtual environment."
        Invoke-Pause
        Exit 1
    }
}

# ==============================================================================
# 3. Upgrade pip
# ==============================================================================
Write-Output "[INFO] Upgrading pip..."
& "$venvPath\Scripts\python" -m pip install --upgrade pip

# ==============================================================================
# 3.5 Install Poetry
# ==============================================================================
Write-Output "[INFO] Installing Poetry in .venv..."
& "$venvPath\Scripts\python" -m pip install poetry==2.4.1

# ==============================================================================
# 4. Install Python Dependencies
# ==============================================================================
Write-Output "[INFO] Installing runtime dependencies from pyproject.toml..."
try {
    & "$venvPath\Scripts\python" -m poetry config --local virtualenvs.in-project true
    & "$venvPath\Scripts\python" -m poetry config --local virtualenvs.create false
    & "$venvPath\Scripts\python" -m poetry -v install --only main,ml-heavy
    if ($LASTEXITCODE -ne 0) {
        throw "Poetry install failed with exit code $LASTEXITCODE"
    }

    # [FIX] We use a specific havsfunc r33 script for QTGMC compatibility.
    # We download it directly instead of using pip to avoid pulling unnecessary/failing dependencies.
    Write-Output "[INFO] Setting up havsfunc r33 script with integrity verification..."
    $havsfuncExpectedSha256 = "4DA2839544B1CE9382DB670B069DC358228251D147DAD91F740A860840E04924"
    $havsfuncDest = "$venvPath\Lib\site-packages\havsfunc.py"
    if (Test-Path "$venvPath\Lib\site-packages\havsfunc") { Remove-Item "$venvPath\Lib\site-packages\havsfunc" -Recurse -Force }
    
    $havsfuncSuccess = $false
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        if (Test-Path $havsfuncDest) { Remove-Item -Path $havsfuncDest -Force -ErrorAction SilentlyContinue }
        try {
            Invoke-WebRequest -Uri "https://raw.githubusercontent.com/HomeOfVapourSynthEvolution/havsfunc/r33/havsfunc.py" -OutFile $havsfuncDest
            
            $havsfuncDownloadedHash = (Get-FileHash -Path $havsfuncDest -Algorithm SHA256).Hash
            if ($havsfuncDownloadedHash -eq $havsfuncExpectedSha256) {
                $havsfuncSuccess = $true
                break
            }
            else {
                Write-Output "   -> [WARNING] havsfunc.py SHA256 integrity check failed on attempt $attempt! Expected: $havsfuncExpectedSha256, got: $havsfuncDownloadedHash"
                Remove-Item -Path $havsfuncDest -Force -ErrorAction SilentlyContinue
                Write-Output "      Deleted corrupt file; retrying download..."
            }
        }
        catch {
            $err = $_.Exception.Message
            Write-Output "   -> [WARNING] havsfunc.py download failed on attempt ${attempt}: $err"
            if (Test-Path $havsfuncDest) { Remove-Item -Path $havsfuncDest -Force -ErrorAction SilentlyContinue }
            if ($attempt -lt 3) {
                Write-Output "      Retrying download..."
            }
        }
    }

    if (-not $havsfuncSuccess) {
        throw "havsfunc.py SHA256 integrity check failed after multiple attempts."
    }

    Write-Output "[INFO] Installing pinned mvsfunc dependency..."
    $gitCmd = Get-Command "git.exe" -ErrorAction SilentlyContinue
    if (-not $gitCmd) {
        $gitCmd = Get-Command "git" -ErrorAction SilentlyContinue
    }
    if (-not $gitCmd) {
        Write-Output "[WARNING] git not found; skipping the pinned mvsfunc install."
        Write-Output "   -> Install Git and rerun install.ps1 if QTGMC reports a missing mvsfunc module."
    }
    else {
        $mvsfuncCommit = "865c7486ca860d323754ec4774bc4cca540a7076"
        & "$venvPath\Scripts\python" -m pip install --upgrade "git+https://github.com/HomeOfVapourSynthEvolution/mvsfunc.git@$mvsfuncCommit"
        if ($LASTEXITCODE -ne 0) {
            throw "mvsfunc install failed with exit code $LASTEXITCODE"
        }
    }

    # [FIX] Patch havsfunc for VapourSynth API compatibility
    # The r33 script uses vs.get_core() which is deprecated
    $patchScript = Join-Path $PSScriptRoot "modules\core\patch_havsfunc.py"
    if (Test-Path $patchScript) {
        Write-Output "   -> Patching havsfunc compatibility..."
        & "$venvPath\Scripts\python" $patchScript
    }
}
catch {
    Write-Output "[ERROR] Failed to install dependencies: $_"
    $InstallFailed = $true
}

Write-Output ""
Write-Output "=================================================="
# ==============================================================================
# 5. Install Local FFmpeg (Self-Contained)
# ==============================================================================
$ffmpegDest = "$venvPath\Scripts\ffmpeg.exe"
if ($env:AVD_SKIP_FFMPEG -eq "1") {
    Write-Output "[INFO] AVD_SKIP_FFMPEG=1 set; using system FFmpeg."
}
elseif (-not (Test-Path $ffmpegDest)) {
    Write-Output "[INFO] FFmpeg not found in .venv. Downloading static build with integrity verification..."
    $ffmpegUrl = "https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-9.0.1-essentials_build.zip"
    $ffmpegExpectedSha256 = "FEC81AE03971D9DD4BE3EBE02E263BD2EC1D789483F931BDBA5F5715E65DA2E9"
    $zipPath = Join-Path $PSScriptRoot "ffmpeg.zip"
    $extractPath = Join-Path $PSScriptRoot "ffmpeg_temp"

    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Write-Output "   -> Downloading FFmpeg package..."
        
        $ffmpegSuccess = $false
        for ($attempt = 1; $attempt -le 3; $attempt++) {
            if (Test-Path $zipPath) { Remove-Item $zipPath -Force -ErrorAction SilentlyContinue }
            try {
                Invoke-WebRequest -Uri $ffmpegUrl -OutFile $zipPath -UseBasicParsing

                $downloadedSha256 = (Get-FileHash -Path $zipPath -Algorithm SHA256).Hash
                if ($downloadedSha256 -eq $ffmpegExpectedSha256) {
                    $ffmpegSuccess = $true
                    break
                }
                else {
                    Write-Output "   -> [WARNING] FFmpeg SHA256 checksum mismatch on attempt $attempt! Expected: $ffmpegExpectedSha256, got: $downloadedSha256"
                    Remove-Item $zipPath -Force -ErrorAction SilentlyContinue
                    Write-Output "      Deleted corrupt archive; retrying download..."
                }
            }
            catch {
                $err = $_.Exception.Message
                Write-Output "   -> [WARNING] FFmpeg download failed on attempt ${attempt}: $err"
                if (Test-Path $zipPath) { Remove-Item $zipPath -Force -ErrorAction SilentlyContinue }
                if ($attempt -lt 3) {
                    Write-Output "      Retrying download..."
                }
            }
        }

        if (-not $ffmpegSuccess) {
            throw "FFmpeg SHA256 checksum mismatch after multiple attempts! Expected: $ffmpegExpectedSha256"
        }

        Write-Output "   -> SHA256 verified successfully. Extracting..."
        Expand-Archive -Path $zipPath -DestinationPath $extractPath -Force

        $binPath = Get-ChildItem -Path $extractPath -Recurse -Filter "ffmpeg.exe" | Select-Object -First 1
        if ($binPath) {
            $sourceDir = $binPath.DirectoryName
            Copy-Item -Path "$sourceDir\ffmpeg.exe" -Destination "$venvPath\Scripts\" -Force
            Copy-Item -Path "$sourceDir\ffprobe.exe" -Destination "$venvPath\Scripts\" -Force
            Write-Output "   -> FFmpeg installed to .venv/Scripts/ (Self-Contained & Verified)"
        }
        else {
            throw "Could not find ffmpeg.exe in extracted archive."
        }
    }
    catch {
        Write-Output "[WARNING] Failed to auto-install FFmpeg: $_"
        Write-Output "The app will rely on system-wide FFmpeg instead."
    }
    finally {
        if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
        if (Test-Path $extractPath) { Remove-Item $extractPath -Recurse -Force }
    }
}
else {
    Write-Output "[INFO] Local FFmpeg already installed."
}

Write-Output ""
Write-Output "=================================================="
# ==============================================================================
# 6. Initialize VapourSynth Runtime (pip / Self-Contained)
# ==============================================================================
# We avoid downloading portable ZIP bundles and instead rely on the pip package.
# The local .venv\vs folder is kept for plugin isolation and deterministic runtime paths.
# ==============================================================================
$vsExtractDir = "$venvPath\vs"
if (-not (Test-Path $vsExtractDir)) {
    New-Item -ItemType Directory -Path $vsExtractDir -Force | Out-Null
}

# Keep directory layout deterministic for plugin installers and runtime lookups.
foreach ($dirName in @("vs-plugins", "vs-coreplugins")) {
    $dirPath = Join-Path $vsExtractDir $dirName
    if (-not (Test-Path $dirPath)) {
        New-Item -ItemType Directory -Path $dirPath -Force | Out-Null
    }
}

if (-not (Test-Path "$vsExtractDir\portable.vs")) {
    New-Item -Path "$vsExtractDir\portable.vs" -ItemType File -Force | Out-Null
}

Write-Output "[INFO] Prepared local VapourSynth runtime folder at .venv/vs (pip-backed)."

# ==============================================================================
# 7. Install VapourSynth Plugins (QTGMC Stack)
# ==============================================================================
Write-Output "=================================================="
Write-Output "[INFO] Installing VapourSynth Plugins (QTGMC Stack)..."
$vsExtractDir = "$venvPath\vs"
$venvPython = "$venvPath\Scripts\python.exe"
$pluginsToInstall = "havsfunc lsmas mvtools nnedi3 nnedi3cl neo_fft3d removegrain fmtconv ffms2 eedi3 eedi3m"

# [R77 STANDARD] Use standard folder names as required by VapourSynth
$pluginsDirName = "vs-plugins"
$corePluginsDirName = "vs-coreplugins"

# Ensure we have a modern Python package with vspipe.exe available in site-packages.
try {
    Write-Output "   -> Ensuring Python vapoursynth package is installed (target: 77)..."
    & $venvPython -m pip install --upgrade "vapoursynth==77" | Out-Null

    Write-Output "   -> Registering VapourSynth runtime configuration..."
    & "$venvPath\Scripts\vapoursynth.exe" register-install | Out-Null
    & "$venvPath\Scripts\vapoursynth.exe" register-legacy-install | Out-Null

    # Force the VSScript -> Python mapping to the active venv and base Python DLL.
    # This avoids stale entries (e.g. old python313.dll) after Python version migrations.
    $vsScriptPath = (& "$venvPath\Scripts\vapoursynth.exe" get-vsscript).Trim()
    $basePythonDll = (& $venvPython -c "import os, sys; c=[os.path.join(sys.base_prefix, f'python{sys.version_info.major}{sys.version_info.minor}.dll'), os.path.join(sys.base_exec_prefix, f'python{sys.version_info.major}{sys.version_info.minor}.dll')]; e=[p for p in c if os.path.exists(p)]; print(e[0] if e else '')").Trim()

    if ($vsScriptPath -and $basePythonDll) {
        $vsConfigDir = Join-Path $env:APPDATA "vapoursynth"
        $vsConfigFile = Join-Path $vsConfigDir "vapoursynth.toml"
        $escapedKey = $vsScriptPath.ToLower().Replace("\", "\\")
        $escapedExe = $venvPython.Replace("\", "\\")
        $escapedDll = $basePythonDll.Replace("\", "\\")

        if (-not (Test-Path $vsConfigDir)) {
            New-Item -ItemType Directory -Path $vsConfigDir -Force | Out-Null
        }

        $mappingLine = ('"' + $escapedKey + '" = ["' + $escapedExe + '","' + $escapedDll + '"]')
        $existingConfigLines = @()
        if (Test-Path $vsConfigFile) {
            $existingConfigLines = Get-Content -Path $vsConfigFile -ErrorAction SilentlyContinue
        }

        $escapedKeyRegex = [regex]::Escape($escapedKey)
        $mergedConfigLines = @()
        $updatedMapping = $false

        foreach ($line in $existingConfigLines) {
            if ($line -match ('^\s*"' + $escapedKeyRegex + '"\s*=')) {
                if (-not $updatedMapping) {
                    $mergedConfigLines += $mappingLine
                    $updatedMapping = $true
                }
                continue
            }
            $mergedConfigLines += $line
        }

        if (-not $updatedMapping) {
            if ($mergedConfigLines.Count -gt 0 -and $mergedConfigLines[-1] -ne "") {
                $mergedConfigLines += ""
            }
            $mergedConfigLines += $mappingLine
        }

        Set-Content -Path $vsConfigFile -Value $mergedConfigLines -Encoding UTF8
        Write-Output "   -> Wrote VapourSynth Python mapping to $vsConfigFile"
    }
    else {
        Write-Output "   -> [NOTICE] Could not resolve complete VapourSynth Python mapping automatically."
    }
}
catch {
    Write-Output "[ERROR] Failed to install or register vapoursynth==77 in venv: $_"
    $InstallFailed = $true
}

# Install vsrepo separately for newer VapourSynth releases.
try {
    Write-Output "   -> Installing vsrepo tool in venv..."
    & $venvPython -m pip install --upgrade vsrepo | Out-Null
}
catch {
    Write-Output "[ERROR] Failed to install vsrepo in venv: $_"
    $InstallFailed = $true
}

# Bootstrap vspipe.exe and required VapourSynth runtime binaries from the pip package.
$vapoursynthPackageDir = Join-Path $venvPath "Lib\site-packages\vapoursynth"
if (-not (Test-Path $vsExtractDir)) { New-Item -ItemType Directory -Path $vsExtractDir -Force | Out-Null }

$venvVspipe = Join-Path $vapoursynthPackageDir "vspipe.exe"
if (Test-Path $venvVspipe) {
    Copy-Item -Path $venvVspipe -Destination (Join-Path $vsExtractDir "vspipe.exe") -Force
    Write-Output "   -> Bootstrapped vspipe.exe from venv site-packages."
}
else {
    Write-Output "[WARNING] vspipe.exe not found in venv site-packages after vapoursynth install."
}

if (Test-Path $vapoursynthPackageDir) {
    $runtimeFiles = @()
    foreach ($pattern in @("*.dll", "*.pyd")) {
        $runtimeFiles += Get-ChildItem -Path $vapoursynthPackageDir -Filter $pattern -File -ErrorAction SilentlyContinue
    }

    if ($runtimeFiles.Count -gt 0) {
        foreach ($runtimeFile in $runtimeFiles) {
            Copy-Item -Path $runtimeFile.FullName -Destination (Join-Path $vsExtractDir $runtimeFile.Name) -Force
        }
        Write-Output "   -> Copied $($runtimeFiles.Count) VapourSynth runtime binaries to .venv/vs/."
    }
    else {
        Write-Output "[WARNING] No VapourSynth runtime binaries found in $vapoursynthPackageDir"
    }
}
else {
    Write-Output "[WARNING] VapourSynth package directory missing: $vapoursynthPackageDir"
}

# 1. Install Bundled Wheel
# This ensures the Python environment matches the binary version
$wheelDir = Join-Path $vsExtractDir "wheel"
if (Test-Path $wheelDir) {
    $wheel = Get-ChildItem -Path $wheelDir -Filter "vapoursynth-*-$pythonAbiTag-*.whl" | Select-Object -First 1
    if ($wheel) {
        Write-Output "   -> Installing bundled VapourSynth wheel into venv..."
        & $venvPython -m pip install $wheel.FullName --force-reinstall | Out-Null
    }
    else {
        Write-Output "   -> Bundled wheel for $pythonAbiTag not found. Installing from PyPI..."
        & $venvPython -m pip install --upgrade "vapoursynth==77" | Out-Null
    }
}
else {
    Write-Output "   -> Portable wheel directory not found. Keeping existing venv VapourSynth package state."
}

# 2. Sync Portable Markers (Fix for "Autoloading Failed")
# By copying portable.vs and core plugins to site-packages, we ensure the Python module
# initializes correctly even when mixed with system paths.
try {
    $sitePkgs = & $venvPython -c "import site; print(site.getsitepackages()[0])"
    if ((Test-Path $sitePkgs) -and (Test-Path $vsExtractDir)) {
        Write-Output "   -> Syncing portable markers to venv site-packages..."
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
    Write-Output "[WARNING] Failed to sync portable markers: $_"
}

# Resolve vsrepo runner (prefer venv console script).
$vsRepoRunnerType = $null
$vsRepoRunnerPath = $null

$venvVsRepoExe = Join-Path $venvPath "Scripts\vsrepo.exe"
if (Test-Path $venvVsRepoExe) {
    $vsRepoRunnerType = "exe"
    $vsRepoRunnerPath = $venvVsRepoExe
}

if (-not $vsRepoRunnerPath) {
    $venvVsRepoPy = Join-Path $venvPath "Lib\site-packages\vsrepo\vsrepo.py"
    if (Test-Path $venvVsRepoPy) {
        $vsRepoRunnerType = "script"
        $vsRepoRunnerPath = $venvVsRepoPy
    }
}

if (-not $vsRepoRunnerPath) {
    $possibleVsRepoPaths = @(
        "$vsExtractDir\vsrepo.py",
        "$vsExtractDir\Scripts\vsrepo.py",
        "$vsExtractDir\sdk\vsrepo.py"
    )
    foreach ($path in $possibleVsRepoPaths) {
        if (Test-Path $path) {
            $vsRepoRunnerType = "script"
            $vsRepoRunnerPath = $path
            break
        }
    }
    if (-not $vsRepoRunnerPath) {
        $foundVsRepo = Get-ChildItem -Path $vsExtractDir -Recurse -Filter "vsrepo.py" -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($foundVsRepo) {
            $vsRepoRunnerType = "script"
            $vsRepoRunnerPath = $foundVsRepo.FullName
        }
    }
}

if ($vsRepoRunnerPath -and (Test-Path $vsRepoRunnerPath)) {
    try {
        $hasVsRepo7Zip = Initialize-VsRepo7Zip -VenvPath $venvPath
        if (-not $hasVsRepo7Zip) {
            Write-Output "   -> [NOTICE] vsrepo may fail for archive-based plugins without 7-Zip."
        }

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
            $nativeStderrPreferenceWasSet = $false
            $nativeStderrPreferenceBackup = $false
            $commandErrorActionPreferenceBackup = $ErrorActionPreference
            if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
                $nativeStderrPreferenceWasSet = $true
                $nativeStderrPreferenceBackup = $PSNativeCommandUseErrorActionPreference
                $PSNativeCommandUseErrorActionPreference = $false
            }

            # vsrepo writes informative diagnostics to stderr; handle success/failure via exit code checks here.
            $ErrorActionPreference = "SilentlyContinue"

            Write-Output "   -> Using vsrepo runner: $vsRepoRunnerPath"
            Write-Output "   -> Updating vsrepo definitions..."
            $useLegacyVsRepoArgs = $false

            if ($vsRepoRunnerType -eq "exe") {
                & $vsRepoRunnerPath update
            }
            else {
                & $venvPython $vsRepoRunnerPath update
            }

            if ($LASTEXITCODE -ne 0) {
                Write-Output "   -> [NOTICE] vsrepo definition update failed; continuing with bundled definitions."
            }

            Write-Output "   -> Running vsrepo install for: $pluginsToInstall"
            $pluginArgs = $pluginsToInstall -split " "
            $installOutput = @()

            # Use -ErrorAction SilentlyContinue and manual check to avoid failing on optional plugins
            if (-not $useLegacyVsRepoArgs) {
                if ($vsRepoRunnerType -eq "exe") {
                    $installOutput = & $vsRepoRunnerPath install $pluginArgs 2>&1
                }
                else {
                    $installOutput = & $venvPython $vsRepoRunnerPath install $pluginArgs 2>&1
                }

                $installOutput | ForEach-Object { Write-Output $_ }

                if ($LASTEXITCODE -ne 0) {
                    Write-Output "   -> [NOTICE] Modern vsrepo install call failed; retrying with legacy -p syntax."
                    $useLegacyVsRepoArgs = $true
                }
            }

            if ($useLegacyVsRepoArgs) {
                if ($vsRepoRunnerType -eq "exe") {
                    $installOutput = & $vsRepoRunnerPath -p install $pluginArgs 2>&1
                }
                else {
                    $installOutput = & $venvPython $vsRepoRunnerPath -p install $pluginArgs 2>&1
                }

                $installOutput | ForEach-Object { Write-Output $_ }
            }

            $requiredPluginNamespaces = @("havsfunc", "lsmas", "mv", "nnedi3", "nnedi3cl", "neo_fft3d", "rgvs", "fmtc", "ffms2", "eedi3", "eedi3m")
            if ($vsRepoRunnerType -eq "exe") {
                $installedOutputText = (& $vsRepoRunnerPath installed 2>&1 | Out-String)
            }
            else {
                $installedOutputText = (& $venvPython $vsRepoRunnerPath installed 2>&1 | Out-String)
            }

            $missingRequiredPlugins = @()
            foreach ($namespace in $requiredPluginNamespaces) {
                $escapedNamespace = [regex]::Escape($namespace)
                if ($installedOutputText -notmatch "(?m)\s$escapedNamespace\s") {
                    $missingRequiredPlugins += $namespace
                }
            }

            if ($LASTEXITCODE -eq 0 -or $missingRequiredPlugins.Count -eq 0) {
                Write-Output "   -> Plugins installed successfully."

                if ($installOutput -match "ZNEDI3") {
                    Write-Output "   -> [NOTICE] ZNEDI3 download currently fails upstream in vsrepo metadata."
                    Write-Output "   -> [NOTICE] QTGMC still works because NNEDI3/NNEDI3CL are installed."
                }
            }
            else {
                Write-Output "   -> [NOTICE] Some required plugins are missing: $($missingRequiredPlugins -join ', ')"
                Write-Output "   -> [NOTICE] QTGMC may require manual plugin setup."
            }

            # Install vsutil (often needed helper)
            & $venvPython -m pip install vsutil | Out-Null

            if ($nativeStderrPreferenceWasSet) {
                $PSNativeCommandUseErrorActionPreference = $nativeStderrPreferenceBackup
            }
            $ErrorActionPreference = $commandErrorActionPreferenceBackup
        }
        finally {
            if ($nativeStderrPreferenceWasSet) {
                $PSNativeCommandUseErrorActionPreference = $nativeStderrPreferenceBackup
            }
            $ErrorActionPreference = $commandErrorActionPreferenceBackup
            $env:APPDATA = $oldAppData
            $env:LOCALAPPDATA = $oldLocalAppData
            Set-Location -Path $originalLocation
        }
    }
    catch {
        Write-Output "[WARNING] Failed to install plugins automatically: $_"
        Write-Output "   -> This can be caused by missing extraction tools (e.g. 7z) or unavailable plugin release assets."
        Write-Output "   -> You can still run the app, but QTGMC may require manual plugin setup."
    }
}
else {
    Write-Output "[ERROR] vsrepo is not available (no console script or script file found)."
    $InstallFailed = $true
}

Write-Output ""
Write-Output "=================================================="
# ==============================================================================
# 8. Generate Launcher (start.bat)
# ==============================================================================
Write-Output "Generating launcher: start.bat..."
$batchContent = @"
@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" if not exist ".VENV\Scripts\python.exe" (
    echo [INFO] Virtual environment not found. Running automatic installation...
    powershell -ExecutionPolicy Bypass -File "%~dp0install.ps1"
    if %errorlevel% neq 0 (
        echo [ERROR] Installation failed.
        pause
        exit /b 1
    )
)

echo Starting Auto-VHS-Deinterlacer...
REM Safely forward all drag-and-drop arguments with strict parameter quoting
set "CMD_ARGS="
:loop_args
if "%~1"=="" goto run_app
set CMD_ARGS=%CMD_ARGS% "%~1"
shift
goto loop_args

:run_app
set "PYTHON_EXE=.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=.VENV\Scripts\python.exe"
"%PYTHON_EXE%" auto_deinterlancer.py %CMD_ARGS%

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

if ($InstallFailed) {
    Write-Output "`n=================================================="
    Write-Output "[ERROR] Installation completed with errors."
    Write-Output "Some components may not be working correctly."
    Write-Output "Check the logs above for red [ERROR] and orange [WARNING] messages."
    Write-Output "=================================================="
}
else {
    Write-Output "`nInstallation Complete!"
    Write-Output "You can now Run the application by:"
    Write-Output "1. Double-clicking 'start.bat'"
    Write-Output "2. Dragging video files onto 'start.bat'"
    Write-Output "Done."
}

Write-Output ""
Invoke-Pause

if ($InstallFailed) { Exit 1 }
Exit 0
